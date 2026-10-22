"""Render only our fixed scene class. AI input is JSON, never Python or TeX."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

from ..config import ROOT, settings
from ..models import Animation
from .animation_layout import node_positions
from .checkpoints import fingerprint, save_json
from .diagnostics import record
from .process import run_process

WIDTH, HEIGHT, FPS = 1696, 480, 30
PALETTES = {
    'motion': {'bg': '#101e32', 'fg': '#f3f7fc', 'accent': '#4fdbc4', 'muted': '#99afc9'},
    'whiteboard': {'bg': '#faf9f4', 'fg': '#203245', 'accent': '#008779', 'muted': '#6a7887'},
    'slides': {'bg': '#edf2f8', 'fg': '#172c46', 'accent': '#2664db', 'muted': '#667c93'},
}


def timed_animation(scene: dict, audio_seconds: float) -> dict | None:
    if not scene.get('animation'):
        return None
    animation = Animation.model_validate(scene['animation']).model_dump()
    position = -1
    for state in animation['states']:
        position = scene['narration'].index(state['cue'], max(0, position + 1))
        state['at_frame'] = round(position / len(scene['narration']) * audio_seconds * FPS)
    if animation['states'][0]['at_frame'] != 0:
        # Keep the concrete initial input visible before the first spoken transition.
        animation['states'][0]['at_frame'] = 0
    if animation['template'] in {'graph', 'tree'}:
        animation['positions'] = node_positions(animation)
    return animation


async def render_manim(animation: dict, frames: int, style: str, workdir: Path) -> Path:
    template = ROOT / 'backend/app/services/manim_templates.py'
    payload = {'animation': animation, 'frames': frames, 'palette': PALETTES[style]}
    key = fingerprint([payload, hashlib.sha256(template.read_bytes()).hexdigest(), settings.manim_python])
    directory = workdir / 'manim' / key
    directory.mkdir(parents=True, exist_ok=True)
    clip = directory / 'clip.mp4'
    if clip.exists():
        try:
            await validate_clip(clip, frames)
            record('検証済みのManim映像を再利用します', level='success')
            return clip
        except (RuntimeError, ValueError, KeyError):
            clip.unlink(missing_ok=True)
    payload_path = directory / 'input.json'
    save_json(payload_path, payload)
    env = os.environ.copy()
    env['LECTURE_MANIM_INPUT'] = str(payload_path.resolve())
    python = settings.manim_python or sys.executable
    try:
        code, _, _ = await run_process([python, str(template), str(clip.resolve())],
            cwd=directory, timeout=settings.manim_timeout, env=env, capture_output=False)
    except (OSError, asyncio.TimeoutError) as exc:
        raise RuntimeError('Manimを起動または時間内に描画できません') from exc
    if code or not clip.exists():
        raise RuntimeError('Manimの固定テンプレート描画に失敗しました')
    await validate_clip(clip, frames)
    return clip


async def validate_clip(path: Path, frames: int):
    # Local import avoids a render_service/manim_service import cycle.
    from .render_service import inspect_video
    meta = await inspect_video(path)
    video = next((s for s in meta['streams'] if s['codec_type'] == 'video'), {})
    if (video.get('width'), video.get('height'), video.get('r_frame_rate'), video.get('codec_name')) != (WIDTH, HEIGHT, '30/1', 'h264'):
        raise RuntimeError('Manim映像の解像度・フレームレート・コーデックが不正です')
    if abs(float(meta['format']['duration']) - frames / FPS) > 1 / FPS + .001:
        raise RuntimeError('Manim映像の長さが音声タイムラインと一致しません')
