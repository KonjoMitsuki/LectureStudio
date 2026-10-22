import asyncio
import json
from pathlib import Path
import httpx
import pytest
from backend.app.main import create_app
from backend.app.models import Lecture, GenerationSettings
from backend.app.services.pipeline import Pipeline
from backend.app.storage import Store
from scripts.make_sample_pdf import create


class FakeAnalyzer:
    def __init__(self, lecture):
        self.lecture = Lecture.model_validate(lecture)
        self.calls = 0
    async def analyze(self, *args):
        self.calls += 1
        return self.lecture


class FakeVoice:
    def __init__(self):
        self.fail = True
    async def speakers(self):
        return [{"styles": [{"id": 3}]}]
    async def synthesize(self, text, speaker, speed, cache):
        if self.fail:
            raise httpx.ConnectError("connection refused")
        path = cache / "audio.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"unit-test audio")
        return {"path": str(path), "audio_seconds": 5.0, "duration_in_frames": 165}


async def fake_render(lecture, audio, style, workdir, callback):
    callback(0.5)
    (workdir / "video.mp4").write_bytes(b"unit-test video; real MP4 verified separately")
    return {"path": str(workdir / "video.mp4"), "seconds": 5.5, "chapters": []}


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "sample.pdf"
    create(path)
    return path.read_bytes()


@pytest.fixture
async def client(tmp_path):
    class IdlePipeline:
        def __init__(self, store): self.store = store
        async def start(self): self.store.recover()
        async def stop(self): pass
        def submit(self, project_id, options): return self.store.enqueue(project_id, options.model_dump(), 10)
    app = create_app(tmp_path / "data", IdlePipeline)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
            client.app = app
            yield client


async def test_upload_generate_duplicate_delete_busy_and_diagnostics(client, pdf):
    response = await client.post('/api/projects', files={'file': ('../大学.pdf', pdf, 'application/pdf')})
    assert response.status_code == 201
    item = response.json()
    assert item['filename'] == '大学.pdf'
    project_id = item['id']
    assert (await client.get('/api/projects')).json()[0]['id'] == project_id
    assert (await client.post(f'/api/projects/{project_id}/generate')).status_code == 202
    assert (await client.post(f'/api/projects/{project_id}/generate')).status_code == 409
    assert (await client.delete(f'/api/projects/{project_id}')).status_code == 409
    diagnostics = (await client.get(f'/api/projects/{project_id}/diagnostics')).json()
    assert 'source.pdf' in diagnostics['artifacts'] and len(diagnostics['jobs']) == 1
    assert (await client.get(f'/api/projects/{project_id}/video')).status_code == 409


@pytest.mark.parametrize('name,content', [('evil.txt', b'%PDF-'), ('evil.pdf', b'not a pdf'), ('file.pdf', b'')])
async def test_upload_checks_filename_and_magic(client, name, content):
    assert (await client.post('/api/projects', files={'file': (name, content)})).status_code == 400
    assert (await client.get('/api/projects')).json() == []


async def test_unsafe_origin_host_settings_and_paths(client, pdf):
    assert (await client.post('/api/projects', files={'file': ('x.pdf', pdf)}, headers={'Origin': 'https://evil.example'})).status_code == 403
    assert (await client.get('/api/projects', headers={'Host': 'evil.example'})).status_code == 400
    assert (await client.post('/api/projects', files={'file': ('x.pdf', pdf)}, data={'options': '{"speaker":-1}'})).status_code == 422
    assert (await client.get('/api/projects/not-a-uuid')).status_code == 404
    assert (await client.get('/api/projects/00000000000000000000000000000000/pages/999')).status_code == 404


async def test_upload_size_limit_stream_and_cleanup(client, monkeypatch):
    from backend.app.config import settings
    monkeypatch.setattr(settings, 'max_upload_mb', 1)
    response = await client.post('/api/projects', files={'file': ('large.pdf', b'%PDF-' + b'x' * (1024 * 1024))})
    assert response.status_code == 413
    assert (await client.get('/api/projects')).json() == []


async def test_response_range_and_download(client, pdf):
    item = (await client.post('/api/projects', files={'file': ('sample.pdf', pdf)})).json()
    store = client.app.state.store
    store.update(item['id'], status='completed', stage='completed')
    path = store.directory(item['id']) / 'video.mp4'
    path.write_bytes(b'0123456789')
    response = await client.get(f"/api/projects/{item['id']}/video", headers={'Range': 'bytes=2-5'})
    assert response.status_code == 206 and response.content == b'2345'
    download = await client.get(f"/api/projects/{item['id']}/video?download=true")
    assert 'attachment' in download.headers['content-disposition']
    assert (await client.delete(f"/api/projects/{item['id']}")).status_code == 204
    assert not store.directory(item['id']).exists()


async def test_failure_recovery_keeps_validated_script_and_reuses_analyzer(tmp_path, valid_lecture):
    store = Store(tmp_path / 'data')
    analyzer = FakeAnalyzer(valid_lecture)
    voice = FakeVoice()
    pipeline = Pipeline(store, analyzer, voice, fake_render)
    project = store.create('lecture.pdf', GenerationSettings(duration='test').model_dump())
    workdir = store.directory(project['id'])
    workdir.mkdir(parents=True)
    create(workdir / 'source.pdf')
    first = store.enqueue(project['id'], project['settings'], 10)
    await pipeline.run(project['id'], first)
    failed = store.get(project['id'])
    assert failed['status'] == 'failed' and failed['stage'] == 'audio'
    assert (workdir / 'lecture.json').exists() and analyzer.calls == 1
    assert json.loads((workdir / 'error.json').read_text())['type'] == 'ConnectError'
    first_events = store.events(project['id'], first)
    assert first_events[-1]['level'] == 'error'
    assert any('台本が完成' in event['message'] for event in first_events)
    assert '線形探索' not in json.dumps(first_events, ensure_ascii=False)
    assert valid_lecture['scenes'][0]['narration'] not in json.dumps(first_events, ensure_ascii=False)
    assert store.activity(project['id'])['completed_stages'] == ['pdf', 'ai']
    voice.fail = False
    second = store.enqueue(project['id'], project['settings'], 10)
    await pipeline.run(project['id'], second)
    assert store.get(project['id'])['status'] == 'completed'
    assert analyzer.calls == 1
    assert [row['status'] for row in store.job_history(project['id'])] == ['completed', 'failed']
    assert store.events(project['id'], first) == first_events
    assert store.activity(project['id'])['completed_stages'] == ['pdf', 'ai', 'audio', 'render']
    assert store.events(project['id'], second)[-1]['level'] == 'success'


def test_restart_recovery(tmp_path):
    store = Store(tmp_path / 'data')
    item = store.create('lecture.pdf', GenerationSettings().model_dump())
    job_id = store.enqueue(item['id'], item['settings'], 10)
    store.update(item['id'], status='running', stage='render')
    store.job(job_id, 'running', 'render')
    assert store.recover() == []
    assert store.get(item['id'])['status'] == 'failed'
    assert store.job_history(item['id'])[0]['status'] == 'failed'


async def test_invalid_cached_script_is_preserved_and_regenerated(tmp_path, valid_lecture):
    store = Store(tmp_path / 'data')
    analyzer = FakeAnalyzer(valid_lecture)
    voice = FakeVoice(); voice.fail = False
    pipeline = Pipeline(store, analyzer, voice, fake_render)
    project = store.create('lecture.pdf', GenerationSettings(duration='test').model_dump())
    directory = store.directory(project['id']); directory.mkdir(parents=True)
    create(directory / 'source.pdf')
    first = store.enqueue(project['id'], project['settings'], 10)
    await pipeline.run(project['id'], first)
    (directory / 'lecture.json').write_text('{"broken":"cache"}')
    second = store.enqueue(project['id'], project['settings'], 10)
    await pipeline.run(project['id'], second)
    assert store.get(project['id'])['status'] == 'completed'
    assert analyzer.calls == 2
    assert (directory / 'lecture.invalid.json').exists()


async def test_second_worker_cannot_use_same_data_directory(tmp_path):
    first = create_app(tmp_path / 'data')
    second = create_app(tmp_path / 'data')
    async with first.router.lifespan_context(first):
        with pytest.raises(RuntimeError, match='1プロセス'):
            async with second.router.lifespan_context(second):
                pytest.fail('second worker started')


async def test_readable_diagnostics_export_and_attempt_selection(client, pdf, valid_lecture):
    from backend.app.services.diagnostics import GenerationLog
    item = (await client.post('/api/projects', files={'file': ('sample.pdf', pdf)})).json()
    store = client.app.state.store
    project_id = item['id']
    base = f'/api/projects/{project_id}'
    first = store.enqueue(project_id, item['settings'], 10)
    log = GenerationLog(store, project_id, first)
    log.begin_stage('ai')
    for i in range(130):
        log.emit(f'内容を確認中：{i}', details=['台本の抜粋：' + 'あ' * 1000])
    store.update(project_id, status='failed', stage='ai')
    store.job(first, 'failed', 'ai', '時間切れ')
    log.emit('AIの待機上限に達しました', level='error', task=True)
    (store.directory(project_id) / 'lecture.json').write_text(json.dumps(valid_lecture, ensure_ascii=False))
    result = (await client.get(base + '/diagnostics')).json()
    assert len(result['events']) == 120 and result['has_more']
    assert result['events'][-1]['level'] == 'error'
    assert len(result['events'][-2]['details'][0]) <= 501
    assert result['activity']['running'] is False
    assert any(a['name'] == 'lecture.json' and a['bytes'] > 0 for a in result['artifact_summaries'])
    transcript = await client.get(base + '/transcript')
    assert '線形探索' in transcript.text and '先頭から順番に値を比較します。' in transcript.text
    assert '区分：元資料の説明' in transcript.text
    valid_lecture['scenes'][0]['supplemental'] = True
    (store.directory(project_id) / 'lecture.json').write_text(json.dumps(valid_lecture, ensure_ascii=False))
    assert '区分：AIによる補足' in (await client.get(base + '/transcript')).text
    exported = await client.get(base + '/logs?download=true')
    assert 'attachment' in exported.headers['content-disposition']
    assert '内容を確認中：0' in exported.text and 'AIの待機上限に達しました' in exported.text
    second = store.enqueue(project_id, item['settings'], 10)
    current = (await client.get(base + '/diagnostics')).json()
    assert current['selected_job_id'] == second and current['activity'] is None and current['events'] == []
    previous = (await client.get(base + f'/diagnostics?job_id={first}')).json()
    assert previous['events'][-1]['level'] == 'error' and previous['activity'] is None
    assert (await client.get(base + '/diagnostics?job_id=unknown')).status_code == 404
    # Events and live snapshots disappear together with the project.
    store.update(project_id, status='failed')
    assert (await client.delete(base)).status_code == 204
    assert store.activity(project_id) is None and list(store.export_events(project_id)) == []
