import copy
import json

import pytest

from backend.app.models import GenerationSettings, validate_lecture
from backend.app.services.captions import build_captions, caption_chunks
from backend.app.services import render_service


@pytest.mark.parametrize('text', [
    '先頭から順番に値を比較します。目的の値が見つかったら終了します。',
    '長い文章' * 50,
    '英語と日本語、ABC、数式x=1。\n次の行も保持します！',
])
def test_captions_retain_text_and_have_contiguous_audio_boundaries(text):
    captions = build_captions(text, 23.5)
    assert ''.join(c['text'] for c in captions) == text
    assert all(0 < len(c['text']) <= 42 for c in captions)
    assert captions[0]['start_frame'] == 0
    assert captions[-1]['end_frame'] == 705
    assert all(a['end_frame'] == b['start_frame'] for a, b in zip(captions, captions[1:]))
    assert all(c['start_frame'] < c['end_frame'] for c in captions)


def test_sentence_breaks_and_empty_captions():
    assert caption_chunks('値を比較します。見つかれば終了です。') == ['値を比較します。', '見つかれば終了です。']
    assert build_captions('', 10) == []
    assert build_captions('説明', 0) == []


def quiz_lecture(valid_lecture):
    result = copy.deepcopy(valid_lecture)
    question = result['scenes'][0]
    question.update(kind='quiz', thinking_seconds=5, narration='先頭から比較するのはどの探索でしょうか。少し考えてみましょう。')
    answer = copy.deepcopy(question)
    answer.update(id='scene_002', kind='quiz_answer', thinking_seconds=0, narration='正答は線形探索です。先頭から順番に比較するためです。')
    result['scenes'].append(answer)
    return result


def test_quiz_pairs_and_duration_policy(valid_lecture):
    lecture = quiz_lecture(valid_lecture)
    assert validate_lecture(lecture, [1]).scenes[0].thinking_seconds == 5
    assert [GenerationSettings(duration=d).quiz_count for d in ['test', 'short', 'medium', 'long']] == [0, 1, 2, 3]
    lecture['scenes'].pop()
    with pytest.raises(ValueError, match='解説'):
        validate_lecture(lecture, [1])


@pytest.mark.parametrize('mutation', ['answer_only', 'no_wait', 'lecture_wait'])
def test_rejects_invalid_quiz_structure(valid_lecture, mutation):
    lecture = quiz_lecture(valid_lecture)
    if mutation == 'answer_only':
        lecture['scenes'].pop(0)
    elif mutation == 'no_wait':
        lecture['scenes'][0]['thinking_seconds'] = 0
    else:
        lecture['scenes'][1]['thinking_seconds'] = 5
    with pytest.raises(ValueError):
        validate_lecture(lecture, [1])


async def test_render_props_keep_captions_and_quiz_wait_in_chapter_offsets(tmp_path, monkeypatch, valid_lecture):
    lecture = quiz_lecture(valid_lecture)
    audio_file = tmp_path / 'sound.wav'
    audio_file.write_bytes(b'fake audio')
    audio = [{'path': str(audio_file), 'audio_seconds': 5.0, 'duration_in_frames': 165}] * 2

    async def fake_process(command, **kwargs):
        (tmp_path / 'video.partial.mp4').write_bytes(b'fake video')
        return 0, '', ''

    async def fake_inspect(path):
        return {'format': {'duration': '16.0'}, 'streams': [
            {'codec_type': 'video', 'codec_name': 'h264', 'width': 1920, 'height': 1080, 'r_frame_rate': '30/1'},
            {'codec_type': 'audio', 'codec_name': 'aac'},
        ]}

    monkeypatch.setattr(render_service, 'run_process', fake_process)
    monkeypatch.setattr(render_service, 'inspect_video', fake_inspect)
    result = await render_service.render_video(lecture, audio, 'motion', tmp_path)
    props = json.loads((tmp_path / 'render_props.json').read_text())
    question, answer = props['scenes']
    assert question['duration_in_frames'] == 315
    assert question['thinking_start_frame'] == 165
    assert question['captions'][-1]['end_frame'] == 150
    assert answer['start_frame'] == 315
    assert props['duration_in_frames'] == 480
    assert result['chapters'][1]['seconds'] == 10.5


async def test_analyzer_retries_missing_quiz_and_requests_duration_specific_count(tmp_path, monkeypatch, valid_lecture):
    from backend.app.services import ai_analyzer
    prompts = []

    async def fake_process(command, **kwargs):
        prompts.append(kwargs['stdin'])
        output = command[command.index('--output-last-message') + 1]
        from pathlib import Path
        if Path(output).name.startswith('plan_'):
            value = {'topics': [{'id': 'topic_0001', 'title': '探索', 'source_page': 1, 'source_excerpt': '探索の講義'}],
                'pages': [{'page': 1, 'status': 'content', 'reason': ''}]}
        elif len(prompts) == 2:
            value = valid_lecture
        else:
            value = quiz_lecture(valid_lecture)
            explanation = copy.deepcopy(valid_lecture['scenes'][0])
            explanation['id'] = 'scene_003'
            value['scenes'].append(explanation)
            value['coverage'] = [{'topic_id': 'topic_0001', 'scene_id': 'scene_003', 'narration_excerpt': explanation['narration']}]
        Path(output).write_text(json.dumps(value, ensure_ascii=False))
        return 0, '', ''

    monkeypatch.setattr(ai_analyzer, 'run_process', fake_process)
    lecture = await ai_analyzer.CodexCLIAnalyzer().analyze(
        {'pages': [{'number': 1, 'text': '探索の講義'}]}, GenerationSettings(duration='short'), tmp_path)
    assert len(prompts) == 3
    assert 'この分割のクイズは1問' in prompts[1]
    assert lecture.scenes[0].kind == 'quiz'
    assert lecture.scenes[1].kind == 'quiz_answer'
