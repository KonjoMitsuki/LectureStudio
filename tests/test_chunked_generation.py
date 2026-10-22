import copy
import json

import pytest

from backend.app.models import GenerationSettings, Lecture, PlanChunk
from backend.app.services import ai_analyzer
from backend.app.services.ai_analyzer import CodexCLIAnalyzer, RetryableGenerationError
from backend.app.services.checkpoints import page_chunks


@pytest.fixture
def source():
    return {'pages': [{'number': i, 'text': f'項目{i}は初学者が順番に学ぶ具体的な説明です。'} for i in range(1, 4)]}


class StubAnalyzer(CodexCLIAnalyzer):
    def __init__(self, scene):
        self.scene = scene
        self.calls = []
        self.fail = None
        self.parent_timeout = False

    async def _generate(self, model, validate, prompt, workdir, prefix=''):
        self.calls.append((model, prompt))
        source = json.JSONDecoder().raw_decode(prompt.split('SOURCE_DATA=')[-1])[0]
        if model is PlanChunk:
            value = {'topics': [{'id': f'topic_{i:04}', 'title': f'項目{i}', 'source_page': p['number'],
                'source_excerpt': p['text']} for i, p in enumerate(source['pages'], 1)],
                'pages': [{'page': p['number'], 'status': 'content', 'reason': ''} for p in source['pages']]}
        else:
            plan = json.JSONDecoder().raw_decode(prompt.split('SOURCE_PLAN=')[-1])[0]
            topics = plan['topics']
            if self.parent_timeout and len(topics) > 1:
                raise RetryableGenerationError('safe timeout')
            if self.fail and any(t['id'] == self.fail for t in topics):
                raise RuntimeError('safe authentication error')
            scenes, coverage = [], []
            for i, topic in enumerate(topics, 1):
                scene = copy.deepcopy(self.scene)
                scene.update(id=f'scene_{i:03}', source_pages=[topic['source_page']], narration=topic['source_excerpt'])
                scenes.append(scene)
                coverage.append({'topic_id': topic['id'], 'scene_id': scene['id'], 'narration_excerpt': scene['narration']})
            value = {'title': '講義', 'learning_goals': ['手順を学ぶ'], 'warnings': [], 'scenes': scenes, 'coverage': coverage}
        return validate(value)


async def test_retry_only_failed_chapter_and_settings_invalidate_script_not_plan(tmp_path, monkeypatch, source, valid_lecture):
    monkeypatch.setattr(ai_analyzer.settings, 'chapter_topics', 1)
    analyzer = StubAnalyzer(valid_lecture['scenes'][0])
    analyzer.fail = 'topic_0002'
    options = GenerationSettings(duration='test')
    with pytest.raises(RuntimeError, match='authentication'):
        await analyzer.analyze(source, options, tmp_path / 'ai')
    assert [m for m, _ in analyzer.calls] == [PlanChunk, Lecture, Lecture]
    assert json.loads((tmp_path / 'ai/chapters.json').read_text())['completed'] == 1
    analyzer.calls.clear()
    analyzer.fail = None
    result = await analyzer.analyze(source, options, tmp_path / 'ai')
    assert len(analyzer.calls) == 2
    assert [s.id for s in result.scenes] == ['scene_001', 'scene_002', 'scene_003']
    assert len(result.coverage) == 3
    analyzer.calls.clear()
    await analyzer.analyze(source, options, tmp_path / 'ai')
    assert analyzer.calls == []
    await analyzer.analyze(source, options.model_copy(update={'level': 'detailed'}), tmp_path / 'ai')
    assert len(analyzer.calls) == 3 and all(m is Lecture for m, _ in analyzer.calls)


async def test_timeout_subdivision_resumes_only_failed_child(tmp_path, monkeypatch, source, valid_lecture):
    monkeypatch.setattr(ai_analyzer.settings, 'chapter_topics', 6)
    analyzer = StubAnalyzer(valid_lecture['scenes'][0])
    analyzer.parent_timeout = True
    analyzer.fail = 'topic_0003'
    options = GenerationSettings(duration='test')
    with pytest.raises(RuntimeError):
        await analyzer.analyze(source, options, tmp_path / 'ai')
    analyzer.calls.clear()
    analyzer.fail = None
    result = await analyzer.analyze(source, options, tmp_path / 'ai')
    assert len(analyzer.calls) == 1
    assert 'topic_0003' in analyzer.calls[0][1]
    assert len(result.coverage) == 3


async def test_plan_pages_and_empty_noncontent_chunks_resume(tmp_path, monkeypatch, source, valid_lecture):
    monkeypatch.setattr(ai_analyzer.settings, 'plan_chunk_pages', 1)
    analyzer = StubAnalyzer(valid_lecture['scenes'][0])
    result = await analyzer.analyze(source, GenerationSettings(duration='test'), tmp_path / 'ai')
    assert sum(m is PlanChunk for m, _ in analyzer.calls) == 3
    assert [e.topic_id for e in result.coverage] == ['topic_0001', 'topic_0002', 'topic_0003']
    assert len(json.loads((tmp_path / 'ai/content_plan.json').read_text())['pages']) == 3


def test_page_chunks_preserve_every_page_without_truncating_dense_page(source):
    source['pages'][1]['text'] = 'x' * 5000
    chunks = page_chunks(source, 3, 1000)
    assert [len(c['pages']) for c in chunks] == [1, 1, 1]
    assert [p['number'] for c in chunks for p in c['pages']] == [1, 2, 3]
    assert chunks[1]['pages'][0]['text'] == source['pages'][1]['text']


async def test_empty_reference_page_chunk_does_not_create_invented_topics(tmp_path, monkeypatch, source, valid_lecture):
    monkeypatch.setattr(ai_analyzer.settings, 'plan_chunk_pages', 1)
    class WithReferencePage(StubAnalyzer):
        async def _generate(self, model, validate, prompt, workdir, prefix=''):
            data = json.JSONDecoder().raw_decode(prompt.split('SOURCE_DATA=')[-1])[0]
            if model is PlanChunk and data['pages'][0]['number'] == 1:
                self.calls.append((model, prompt))
                return validate({'topics': [], 'pages': [{'page': 1, 'status': 'non_content', 'reason': '参考文献のみ'}]})
            return await super()._generate(model, validate, prompt, workdir, prefix)
    source['pages'][0]['text'] = '参考文献'
    analyzer = WithReferencePage(valid_lecture['scenes'][0])
    lecture = await analyzer.analyze(source, GenerationSettings(duration='test'), tmp_path / 'ai')
    plan = json.loads((tmp_path / 'ai/content_plan.json').read_text())
    assert [t['source_page'] for t in plan['topics']] == [2, 3]
    assert len(lecture.coverage) == 2
    assert plan['pages'][0]['status'] == 'non_content'


async def test_failed_plan_subdivision_reuses_successful_child(tmp_path, source, valid_lecture):
    class SplitPlan(StubAnalyzer):
        fail_page = 3
        async def _generate(self, model, validate, prompt, workdir, prefix=''):
            data = json.JSONDecoder().raw_decode(prompt.split('SOURCE_DATA=')[-1])[0]
            if model is PlanChunk:
                if len(data['pages']) > 1:
                    self.calls.append((model, prompt))
                    raise RetryableGenerationError('safe timeout')
                if data['pages'][0]['number'] == self.fail_page:
                    self.calls.append((model, prompt))
                    raise RuntimeError('safe authentication error')
            return await super()._generate(model, validate, prompt, workdir, prefix)
    analyzer = SplitPlan(valid_lecture['scenes'][0])
    with pytest.raises(RuntimeError):
        await analyzer.analyze(source, GenerationSettings(duration='test'), tmp_path / 'ai')
    analyzer.calls.clear()
    analyzer.fail_page = None
    await analyzer.analyze(source, GenerationSettings(duration='test'), tmp_path / 'ai')
    plan_calls = [prompt for model, prompt in analyzer.calls if model is PlanChunk]
    assert len(plan_calls) == 1
    assert json.JSONDecoder().raw_decode(plan_calls[0].split('SOURCE_DATA=')[-1])[0]['pages'][0]['number'] == 3
