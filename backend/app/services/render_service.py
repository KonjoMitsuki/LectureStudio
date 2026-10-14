import asyncio
import json
import shutil
import os
from pathlib import Path
from ..config import ROOT, settings
from .process import run_process


async def render_video(lecture: dict, audio: list[dict], style: str, workdir: Path, on_progress=None) -> dict:
    public = workdir / "render_assets"
    public.mkdir(exist_ok=True)
    scenes = []
    offset = 0
    for scene, sound in zip(lecture["scenes"], audio, strict=True):
        name = f"{scene['id']}.wav"
        shutil.copyfile(sound["path"], public / name)
        scenes.append({**scene, "audio_src": name, "audio_seconds": sound["audio_seconds"],
            "duration_in_frames": sound["duration_in_frames"], "start_frame": offset})
        offset += sound["duration_in_frames"]
    props = {"title": lecture["title"], "scenes": scenes, "style": style, "duration_in_frames": offset}
    props_path = workdir / "render_props.json"
    props_path.write_text(json.dumps(props, ensure_ascii=False))
    output = workdir / "video.partial.mp4"

    def line_callback(line):
        try:
            event = json.loads(line)
            if event.get("type") == "progress" and on_progress:
                on_progress(event["progress"])
        except (json.JSONDecodeError, KeyError):
            pass

    try:
        env = os.environ.copy()
        if settings.chromium_path:
            env["LECTURE_CHROMIUM_PATH"] = settings.chromium_path
        code, out, err = await run_process(["node", str(ROOT / "video/render.mjs"), str(props_path),
            str(public), str(output), str(settings.render_concurrency)], cwd=ROOT / "video",
            timeout=settings.render_timeout, on_line=line_callback, env=env)
    except asyncio.TimeoutError as exc:
        raise RuntimeError("動画レンダリングがタイムアウトしました。台本と音声は保持されています") from exc
    (workdir / "render.log").write_text(out + err)
    if code or not output.exists():
        raise RuntimeError("Remotionのレンダリングに失敗しました。プロジェクト内render.logを確認してください")
    meta = await inspect_video(output)
    expected = offset / 30
    if abs(float(meta["format"]["duration"]) - expected) > 0.15:
        raise RuntimeError("MP4の長さが音声タイムラインと一致しません")
    video = next((s for s in meta["streams"] if s["codec_type"] == "video"), {})
    sound = next((s for s in meta["streams"] if s["codec_type"] == "audio"), {})
    if video.get("codec_name") != "h264" or sound.get("codec_name") != "aac":
        raise RuntimeError("MP4の映像・音声コーデックが不正です")
    if (video.get("width"), video.get("height"), video.get("r_frame_rate")) != (1920, 1080, "30/1"):
        raise RuntimeError("MP4の解像度・フレームレートが不正です")
    final = workdir / "video.mp4"
    output.replace(final)
    (workdir / "video_metadata.json").write_text(json.dumps(meta, indent=2))
    return {"path": str(final), "seconds": expected, "chapters": [
        {"id": s["id"], "title": s["title"], "seconds": s["start_frame"] / 30,
         "source_pages": s["source_pages"], "supplemental": s["supplemental"]} for s in scenes]}


async def inspect_video(path: Path) -> dict:
    code, stdout, stderr = await run_process(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], cwd=path.parent, timeout=30)
    if code:
        raise RuntimeError("FFprobeでMP4を検査できません")
    return json.loads(stdout)
