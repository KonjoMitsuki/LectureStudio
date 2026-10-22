import copy
import json
from pathlib import Path

import pytest

from backend.app.models import Animation, validate_lecture
from backend.app.services import render_service
from backend.app.services.animation_layout import node_positions
from backend.app.services.manim_service import timed_animation
from scripts.verify_manim import examples


@pytest.mark.parametrize('animation', list(examples()))
def test_templates_validate_and_timing_uses_measured_speech(animation):
    scene = {'animation': animation, 'narration': '最初の入力です。次に状態を変えます。'}
    timed = timed_animation(scene, 8)
    assert timed['states'][0]['at_frame'] == 0
    assert 0 < timed['states'][1]['at_frame'] < 240
    if animation['template'] in {'tree', 'graph'}:
        assert timed['positions'] == node_positions(animation)


@pytest.mark.parametrize('mutation', ['code', 'unknown_template', 'target', 'unequal_array', 'nonfinite', 'cycle'])
def test_invalid_animation_cannot_reach_renderer(mutation):
    animation = next(examples())
    if mutation == 'code': animation['python'] = '__import__("os").system("touch /tmp/evil")'
    elif mutation == 'unknown_template': animation['template'] = 'python'
    elif mutation == 'target': animation['states'][0]['highlight'] = ['99']
    elif mutation == 'unequal_array': animation['states'][1]['values'] = [1]
    elif mutation == 'nonfinite': animation['states'][0]['values'][0] = float('nan')
    else:
        animation = list(examples())[1]
        animation['edges'].append({'id': 'ba', 'source': 'b', 'target': 'a', 'label': ''})
    with pytest.raises(ValueError): Animation.model_validate(animation)


def test_old_scene_stays_remotion_and_manim_cues_are_validated(valid_lecture):
    lecture = validate_lecture(valid_lecture, [1])
    assert lecture.scenes[0].renderer == 'remotion' and lecture.scenes[0].animation is None
    valid_lecture['scenes'][0].update(renderer='manim', animation=next(examples()))
    with pytest.raises(ValueError, match='cue'): validate_lecture(valid_lecture, [1])


async def test_manim_unavailable_uses_all_snapshots_and_reserves_captions(tmp_path, monkeypatch, valid_lecture):
    animation = next(examples())
    scene = valid_lecture['scenes'][0]
    scene.update(renderer='manim', animation=animation, narration='最初の入力です。次に状態を変えます。')
    audio = tmp_path / 'audio.wav'
    audio.write_bytes(b'fake; actual media checked separately')
    async def unavailable(*args): raise RuntimeError('fixed safe failure')
    async def renderer(command, **kwargs):
        (tmp_path / 'video.partial.mp4').write_bytes(b'fake MP4')
        return 0, '', ''
    async def inspect(path):
        return {'format': {'duration': '3'}, 'streams': [
            {'codec_type': 'video', 'codec_name': 'h264', 'width': 1920, 'height': 1080, 'r_frame_rate': '30/1'},
            {'codec_type': 'audio', 'codec_name': 'aac'}]}
    monkeypatch.setattr(render_service, 'render_manim', unavailable)
    monkeypatch.setattr(render_service, 'run_process', renderer)
    monkeypatch.setattr(render_service, 'inspect_video', inspect)
    await render_service.render_video(valid_lecture, [{'path': str(audio), 'audio_seconds': 2.5, 'duration_in_frames': 90}], 'motion', tmp_path)
    props = json.loads((tmp_path / 'render_props.json').read_text())
    assert props['scenes'][0]['manim_src'] is None
    assert len(props['scenes'][0]['animation']['states']) == 2
    report = json.loads((tmp_path / 'render_report.json').read_text())[0]
    assert report['actual'] == 'remotion' and report['fallback_reason']
    assert report['viewport']['y'] + report['viewport']['height'] < report['caption_top']
