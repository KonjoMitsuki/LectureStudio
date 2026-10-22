import copy
import json

import pytest
from jsonschema import ValidationError

from backend.app.models import validate_lecture
from backend.app.services.ai_analyzer import validate_generated_lecture
from backend.app.services import render_service
from backend.app.storyboard import Storyboard, timed_storyboard


@pytest.fixture
def composed(valid_lecture):
    scene = valid_lecture['scenes'][0]
    scene['visual'] = None
    scene['narration'] = '候補を並べます。半分を除きます。残りを拡大します。'
    scene['storyboard'] = {
        'intent': '候補が半分になる様子を追う',
        'elements': [
            {'id': 'value', 'kind': 'rect', 'x': 100, 'y': 200, 'width': 160, 'height': 100, 'text': '8'},
            {'id': 'other', 'kind': 'rect', 'x': 300, 'y': 200, 'width': 160, 'height': 100, 'text': '16'}],
        'beats': [
            {'cue': '半分を除きます', 'changes': [{'target': 'other', 'opacity': .1}]},
            {'cue': '残りを拡大します', 'changes': [{'target': 'value', 'x': 600, 'width': 240, 'height': 160, 'font_size': 72}]}]}
    return valid_lecture


def test_free_composition_and_legacy_load_independently(composed, valid_lecture):
    lecture = validate_generated_lecture(composed, [1])
    assert lecture.scenes[0].visual is None
    assert lecture.scenes[0].storyboard.intent
    legacy = copy.deepcopy(composed)
    legacy['scenes'][0].pop('storyboard')
    with pytest.raises(ValueError):
        validate_lecture(legacy, [1])
    # Reading legacy data is still allowed, but new AI output must use composition.
    legacy['scenes'][0]['visual'] = {'type': 'keywords', 'items': ['候補'], 'nodes': [], 'edges': [],
                                  'columns': [], 'rows': [], 'formula': '', 'steps': []}
    assert validate_lecture(legacy, [1]).scenes[0].storyboard is None
    with pytest.raises(ValueError, match='storyboard'):
        validate_generated_lecture(legacy, [1])


@pytest.mark.parametrize('mutation', ['target', 'duplicate', 'bounds', 'later_bounds', 'font', 'text', 'empty_change',
                                     'cue', 'cue_order', 'code', 'nan', 'renderer', 'transition_text'])
def test_bad_compositions_never_reach_renderer(composed, mutation):
    scene = composed['scenes'][0]
    board = scene['storyboard']
    if mutation == 'target': board['beats'][0]['changes'][0]['target'] = 'missing'
    elif mutation == 'duplicate': board['elements'].append(board['elements'][0])
    elif mutation == 'bounds': board['elements'][0]['x'] = 1690
    elif mutation == 'later_bounds': board['beats'][1]['changes'][0]['x'] = 1600
    elif mutation == 'font': board['elements'][0]['font_size'] = 12
    elif mutation == 'text': board['elements'][0]['text'] = '文字を小さくせず分割する必要があります'
    elif mutation == 'empty_change': board['beats'][0]['changes'] = [{'target': 'other'}]
    elif mutation == 'cue': board['beats'][0]['cue'] = '台本にない原文'
    elif mutation == 'cue_order': board['beats'].reverse()
    elif mutation == 'code': board['elements'][0]['html'] = '<script>fetch("https://example.test")</script>'
    elif mutation == 'nan': board['elements'][0]['x'] = float('nan')
    elif mutation == 'renderer': scene['renderer'] = 'manim'
    elif mutation == 'transition_text': board['beats'][1]['changes'][0].update(text='新しい長い文字', width=800)
    with pytest.raises((ValueError, ValidationError)):
        validate_lecture(composed, [1])


def test_measured_audio_sets_cues_and_caps_end_transition(composed):
    scene = composed['scenes'][0]
    timed = timed_storyboard(scene, 1)
    narration = scene['narration']
    assert timed['beats'][0]['at_frame'] == round(narration.index('半分') / len(narration) * 30)
    assert timed['beats'][1]['at_frame'] > timed['beats'][0]['at_frame']
    assert all(b['at_frame'] + b['duration_in_frames'] <= 45 for b in timed['beats'])
    assert 'at_frame' not in scene['storyboard']['beats'][0]
    assert timed_storyboard({'narration': '旧シーン'}, 1) is None


def test_arrows_support_reverse_direction_and_markup_is_plain_text():
    board = Storyboard.model_validate({'intent': '左への流れ', 'elements': [
        {'id': 'arrow', 'kind': 'arrow', 'x': 500, 'y': 200, 'width': -200, 'height': -100},
        {'id': 'literal', 'kind': 'text', 'x': 10, 'y': 10, 'width': 1600, 'height': 100, 'text': '<script>hello</script>'}]})
    assert board.elements[0].width == -200


def test_measured_timing_rejects_text_that_only_fits_after_interrupted_growth(composed):
    scene = composed['scenes'][0]
    scene['narration'] = '拡大します。次です。'
    scene['storyboard']['beats'] = [
        {'cue': '拡大', 'transition_seconds': 2, 'changes': [{'target': 'value', 'width': 1000}]},
        {'cue': '次です', 'transition_seconds': 0.5, 'changes': [{'target': 'value', 'text': 'まだ大きくなっていません'}]}]
    validate_lecture(composed, [1])  # Final declared states fit.
    with pytest.raises(ValueError, match='文字'):
        timed_storyboard(scene, .5)  # But the new text arrives during growth.


async def test_render_pipeline_times_composition_and_keeps_subtitles_separate(tmp_path, monkeypatch, composed):
    audio = tmp_path / 'input.wav'
    audio.write_bytes(b'mocked audio: real media tested by verify_storyboard.py')
    async def process(command, **kwargs):
        (tmp_path / 'video.partial.mp4').write_bytes(b'mocked video')
        return 0, '', ''
    async def inspect(path):
        return {'format': {'duration': '4.5'}, 'streams': [
            {'codec_type': 'video', 'codec_name': 'h264', 'width': 1920, 'height': 1080, 'r_frame_rate': '30/1'},
            {'codec_type': 'audio', 'codec_name': 'aac'}]}
    monkeypatch.setattr(render_service, 'run_process', process)
    monkeypatch.setattr(render_service, 'inspect_video', inspect)
    await render_service.render_video(validate_lecture(composed, [1]).model_dump(), [
        {'path': str(audio), 'audio_seconds': 4, 'duration_in_frames': 135}], 'motion', tmp_path)
    props = json.loads((tmp_path / 'render_props.json').read_text())
    assert props['scenes'][0]['storyboard']['beats'][0]['at_frame'] > 0
    assert props['scenes'][0]['captions']
    assert props['scenes'][0]['manim_src'] is None
    report = json.loads((tmp_path / 'render_report.json').read_text())[0]
    assert report['composition'] == 'storyboard'
    assert report['viewport']['y'] + report['viewport']['height'] < report['caption_top']
