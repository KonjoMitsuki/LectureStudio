import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from backend.app.models import GenerationSettings, validate_lecture
from backend.app.services import ai_analyzer
from backend.app.services.coverage import coverage_warnings, validate_content_plan, validate_coverage


@pytest.fixture
def document():
    return {'pages': [
        {'number': 1, 'text': '線形探索は先頭から順番に値を比較します。'},
        {'number': 2, 'text': '二分探索は整列済みの配列が必要です。'},
        {'number': 3, 'text': '参考文献'},
        {'number': 4, 'text': ''},
    ]}


@pytest.fixture
def raw_plan():
    return {'topics': [
        {'id': 'topic_0001', 'title': '線形探索の手順', 'source_page': 1, 'source_excerpt': '先頭から順番に値を比較します。'},
        {'id': 'topic_0002', 'title': '二分探索の前提条件', 'source_page': 2, 'source_excerpt': '整列済みの配列が必要です。'},
    ], 'pages': [
        {'page': 1, 'status': 'content', 'reason': ''},
        {'page': 2, 'status': 'content', 'reason': ''},
        {'page': 3, 'status': 'non_content', 'reason': '参考文献のみ'},
        {'page': 4, 'status': 'unreadable', 'reason': '文字が抽出できない'},
    ]}


def covered_script(valid_lecture):
    result = copy.deepcopy(valid_lecture)
    second = copy.deepcopy(result['scenes'][0])
    second.update(id='scene_002', title='二分探索の前提', narration='二分探索では、配列が整列済みである必要があります。', source_pages=[2])
    result['scenes'].append(second)
    result['coverage'] = [
        {'topic_id': 'topic_0001', 'scene_id': 'scene_001', 'narration_excerpt': result['scenes'][0]['narration']},
        {'topic_id': 'topic_0002', 'scene_id': 'scene_002', 'narration_excerpt': second['narration']},
    ]
    return result


def test_plan_accounts_for_all_pages_and_reports_unreadable_limits(document, raw_plan):
    plan = validate_content_plan(raw_plan, document)
    warnings = coverage_warnings(plan)
    assert len(warnings) == 2
    assert 'p.3' in warnings[0] and '参考文献' in warnings[0]
    assert 'p.4' in warnings[1] and '網羅を確認できない' in warnings[1]


@pytest.mark.parametrize('mutation', ['missing_page', 'duplicate_page', 'duplicate_topic', 'unlisted_page', 'invented_excerpt', 'empty_reason', 'missing_topic', 'excluded_topic'])
def test_plan_rejects_missing_pages_and_invented_source_evidence(document, raw_plan, mutation):
    if mutation == 'missing_page':
        raw_plan['pages'].pop()
    elif mutation == 'duplicate_page':
        raw_plan['pages'].append(raw_plan['pages'][0])
    elif mutation == 'duplicate_topic':
        raw_plan['topics'].append(raw_plan['topics'][0])
    elif mutation == 'unlisted_page':
        raw_plan['topics'][0]['source_page'] = 99
    elif mutation == 'invented_excerpt':
        raw_plan['topics'][0]['source_excerpt'] = '資料にない推測の内容'
    elif mutation == 'empty_reason':
        raw_plan['pages'][-1]['reason'] = ''
    elif mutation == 'missing_topic':
        raw_plan['topics'].pop()
    else:
        raw_plan['pages'][0]['status'] = 'non_content'
    with pytest.raises((ValueError, ValidationError)):
        validate_content_plan(raw_plan, document)


def test_every_topic_is_tied_to_an_actual_explanation(document, raw_plan, valid_lecture):
    script = covered_script(valid_lecture)
    validate_coverage(validate_lecture(script, [1, 2, 3, 4]), validate_content_plan(raw_plan, document))


@pytest.mark.parametrize('mutation', ['missing_topic', 'unknown_topic', 'duplicate_topic', 'unknown_scene', 'wrong_page', 'invented_narration', 'quiz_only'])
def test_coverage_rejects_cosmetic_page_refs_and_unexplained_topics(document, raw_plan, valid_lecture, mutation):
    script = covered_script(valid_lecture)
    if mutation == 'missing_topic':
        script['coverage'].pop()
        # Referencing every page is insufficient without topic explanations.
        script['scenes'][0]['source_pages'] = [1, 2, 3, 4]
    elif mutation == 'unknown_topic':
        script['coverage'][1]['topic_id'] = 'topic_9999'
    elif mutation == 'duplicate_topic':
        script['coverage'].append(script['coverage'][0])
    elif mutation == 'unknown_scene':
        script['coverage'][1]['scene_id'] = 'scene_999'
    elif mutation == 'wrong_page':
        script['scenes'][1]['source_pages'] = [1]
    elif mutation == 'invented_narration':
        script['coverage'][1]['narration_excerpt'] = '実際には説明していない架空のナレーションです。'
    else:
        # Model-valid quiz pair still cannot replace a substantive lecture scene.
        script['scenes'][1].update(kind='quiz', thinking_seconds=5)
        answer = copy.deepcopy(script['scenes'][1])
        answer.update(id='scene_003', kind='quiz_answer', thinking_seconds=0)
        script['scenes'].append(answer)
    with pytest.raises(ValueError):
        validate_coverage(validate_lecture(script, [1, 2, 3, 4]), validate_content_plan(raw_plan, document))


async def test_analyzer_plans_first_and_retries_omitted_later_topic(tmp_path, monkeypatch, document, raw_plan, valid_lecture):
    prompts = []
    script_attempts = 0

    async def fake_process(command, **kwargs):
        nonlocal script_attempts
        prompts.append(kwargs['stdin'])
        output = Path(command[command.index('--output-last-message') + 1])
        if output.name.startswith('plan_'):
            value = raw_plan
        else:
            script_attempts += 1
            value = covered_script(valid_lecture)
            if script_attempts == 1:
                value['coverage'].pop()
        output.write_text(json.dumps(value, ensure_ascii=False))
        return 0, '', ''

    monkeypatch.setattr(ai_analyzer, 'run_process', fake_process)
    workdir = tmp_path / 'ai'
    lecture = await ai_analyzer.CodexCLIAnalyzer().analyze(document, GenerationSettings(duration='test'), workdir)
    assert len(prompts) == 3 and script_attempts == 2
    assert 'SOURCE_PLAN=' not in prompts[0]
    assert 'SOURCE_PLAN=' in prompts[1]
    assert 'topic_0002' in prompts[2] and '未解説の項目' in prompts[2]
    assert '目標秒数（目安）=60' in prompts[1]
    assert '3〜4シーン' not in prompts[1]
    assert len(lecture.coverage) == 2
    report = json.loads((tmp_path / 'coverage.json').read_text())
    assert report['total_topics'] == report['covered_topics'] == 2
    assert len(report['pages']) == 4
    assert (workdir / 'content_plan.json').exists()
    assert any('p.4' in warning for warning in lecture.warnings)

    # Retry/restart uses the same independent plan, never a newly shortened topic list.
    prompts.clear()
    await ai_analyzer.CodexCLIAnalyzer().analyze(document, GenerationSettings(duration='test'), workdir)
    assert len(prompts) == 1 and 'SOURCE_PLAN=' in prompts[0]


def test_embedded_images_are_reported_as_unverified(document, raw_plan):
    document['pages'][0]['images'] = ['diagram.png']
    plan = validate_content_plan(raw_plan, document)
    assert any('画像のみの内容の網羅は未確認' in warning and 'p.1' in warning for warning in coverage_warnings(plan, document))


async def test_repeated_omission_fails_instead_of_shortening_independent_plan(tmp_path, monkeypatch, document, raw_plan, valid_lecture):
    calls = []

    async def fake_process(command, **kwargs):
        output = Path(command[command.index('--output-last-message') + 1])
        calls.append(output.name)
        if output.name.startswith('plan_'):
            value = raw_plan
        else:
            value = covered_script(valid_lecture)
            value['coverage'].pop()
        output.write_text(json.dumps(value, ensure_ascii=False))
        return 0, '', ''

    monkeypatch.setattr(ai_analyzer, 'run_process', fake_process)
    workdir = tmp_path / 'ai'
    with pytest.raises(ValueError, match='網羅性検証'):
        await ai_analyzer.CodexCLIAnalyzer().analyze(document, GenerationSettings(duration='test'), workdir)
    assert calls == ['plan_answer_0.json', 'answer_0.json', 'answer_1.json']
    assert len(json.loads((workdir / 'content_plan.json').read_text())['topics']) == 2
    assert not (tmp_path / 'coverage.json').exists()
