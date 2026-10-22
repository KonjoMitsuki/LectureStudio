import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.models import GenerationSettings, Lecture
from backend.app.services import ai_analyzer, diagnostics, render_service
from backend.app.services.diagnostics import GenerationLog, activity_snapshot, current_log
from backend.app.services.process import run_process
from backend.app.services.pipeline import Pipeline
from backend.app.storage import Store


@pytest.fixture
def log(tmp_path):
    store = Store(tmp_path / 'data')
    project = store.create('lecture.pdf', GenerationSettings().model_dump())
    store.directory(project['id']).mkdir(parents=True)
    job_id = store.enqueue(project['id'], project['settings'], 10)
    return GenerationLog(store, project['id'], job_id)


async def test_heartbeat_continues_during_silent_subprocess_and_timeout_preserves_events(tmp_path, monkeypatch, log):
    monkeypatch.setattr(diagnostics, 'HEARTBEAT_SECONDS', 0.02)
    token = current_log.set(log)
    log.begin_stage('ai')
    task = asyncio.create_task(log.heartbeat())
    initial = log.state['heartbeat_at']
    try:
        with pytest.raises(TimeoutError):
            await run_process([sys.executable, '-c', 'import time; time.sleep(10)'], cwd=tmp_path, timeout=0.15)
        state = log.store.activity(log.project_id)
        assert state['heartbeat_at'] > initial
        assert state['process']['status'] == 'timeout' and state['process']['alive'] is False
        assert state['process']['last_output_at'] is None
        assert any('待機上限に達した' in event['message'] for event in log.store.events(log.project_id, log.state['job_id']))
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        current_log.reset(token)


async def test_live_cli_metadata_survives_timeout_and_never_contains_raw_messages(tmp_path, monkeypatch, log):
    private = 'bearer-secret private-account@example.test 原文テキスト'
    async def timed_out(command, **kwargs):
        callback = kwargs['on_line']
        callback(json.dumps({'type': 'turn.started', 'message': private}))
        callback(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': private}}))
        callback(json.dumps({'type': 'error', 'message': private, 'usage': {'input_tokens': 12, 'secret': private}}))
        raise TimeoutError()
    monkeypatch.setattr(ai_analyzer, 'run_process', timed_out)
    token = current_log.set(log)
    try:
        with pytest.raises(RuntimeError, match='待機上限'):
            await ai_analyzer.CodexCLIAnalyzer()._generate(Lecture, lambda raw: raw, private, tmp_path)
    finally:
        current_log.reset(token)
    records = [json.loads(line) for line in (tmp_path / 'events_0.jsonl').read_text().splitlines()]
    assert len(records) == 3 and records[0]['type'] == 'turn.started'
    assert records[-1]['usage'] == {'input_tokens': 12}
    assert json.loads((tmp_path / 'failure.json').read_text())['reason'] == 'timeout'
    for file in tmp_path.glob('*.json*'):
        assert private not in file.read_text()
    assert private not in json.dumps(log.store.events(log.project_id, log.state['job_id']))


async def test_render_log_is_flushed_before_timeout(tmp_path, monkeypatch, valid_lecture):
    audio = tmp_path / 'sound.wav'
    audio.write_bytes(b'placeholder; renderer mocked')
    async def timed_out(command, **kwargs):
        kwargs['on_line']('{"type":"phase","phase":"frames"}\n')
        kwargs['on_stderr']('render started\n')
        # The file is already readable before the external process finishes.
        assert 'frames' in (tmp_path / 'render.log').read_text()
        raise TimeoutError()
    monkeypatch.setattr(render_service, 'run_process', timed_out)
    with pytest.raises(RuntimeError, match='待機上限'):
        await render_service.render_video(valid_lecture,
            [{'path': str(audio), 'audio_seconds': 5, 'duration_in_frames': 165}], 'motion', tmp_path)
    text = (tmp_path / 'render.log').read_text()
    assert 'frames' in text and 'render started' not in text and '待機上限に達した' in text


def test_snapshot_distinguishes_old_progress_from_fresh_worker_heartbeat(log):
    old = (datetime.now(timezone.utc) - timedelta(minutes=4)).isoformat()
    log.state['last_activity_at'] = old
    snapshot = activity_snapshot(log.state, {'status': 'running'}, {'id': log.state['job_id'], 'finished_at': None})
    assert snapshot['heartbeat_age_seconds'] < 5
    assert snapshot['activity_age_seconds'] >= 240
    assert activity_snapshot(log.state, {'status': 'running'}, {'id': 'different', 'finished_at': None}) is None


async def test_restart_records_interruption_in_the_original_stage(log):
    log.begin_stage('render')
    log.store.update(log.project_id, status='running', stage='render')
    log.store.job(log.state['job_id'], 'running', 'render')
    pipeline = Pipeline(log.store)
    await pipeline.start()
    await pipeline.stop()
    assert log.store.get(log.project_id)['status'] == 'failed'
    event = log.store.events(log.project_id, log.state['job_id'])[-1]
    assert event['level'] == 'error' and event['stage'] == 'render'
    assert 'アプリの終了' in event['message']


async def test_cancellation_marks_the_job_failed_and_keeps_logs(log):
    entered = asyncio.Event()
    class WaitingAnalyzer:
        async def analyze(self, *args):
            entered.set()
            await asyncio.Event().wait()
    directory = log.store.directory(log.project_id)
    (directory / 'document.json').write_text(json.dumps({'page_count': 1, 'warnings': [],
        'pages': [{'number': 1, 'text': '探索の説明', 'headings': []}]}))
    pipeline = Pipeline(log.store, analyzer=WaitingAnalyzer())
    task = asyncio.create_task(pipeline.run(log.project_id, log.state['job_id']))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert log.store.get(log.project_id)['status'] == 'failed'
    event = log.store.events(log.project_id, log.state['job_id'])[-1]
    assert event['level'] == 'error' and event['stage'] == 'ai'
    assert '中断' in event['message']


async def test_usage_is_persisted_live_without_text_or_invalid_values(tmp_path, monkeypatch, log, valid_lecture):
    private = 'PRIVATE_PDF_TEXT_AND_SCRIPT'
    observed = []
    async def process(command, **kwargs):
        for event in [
            {'type': 'turn.started', 'message': private},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': private}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 20, 'output_tokens': 8,
                'cached_input_tokens': 5, 'secret': private}},
        ]:
            kwargs['on_line'](json.dumps(event))
        observed.append(log.store.activity(log.project_id)['ai'])
        from pathlib import Path
        Path(command[command.index('--output-last-message') + 1]).write_text(json.dumps(valid_lecture))
        return 0, '', ''
    monkeypatch.setattr(ai_analyzer, 'run_process', process)
    token = current_log.set(log)
    try:
        await ai_analyzer.CodexCLIAnalyzer()._generate(Lecture, Lecture.model_validate, private, tmp_path)
    finally:
        current_log.reset(token)
    assert observed[0]['usage'] == {'input_tokens': 20, 'output_tokens': 8, 'cached_input_tokens': 5}
    assert observed[0]['event_count'] == 3 and observed[0]['calls'] == 1
    assert any('入力トークン：20' in event['details'] for event in log.store.events(log.project_id, log.state['job_id']))
    assert private not in json.dumps(log.store.activity(log.project_id))
    assert private not in (tmp_path / 'events_0.jsonl').read_text()
    assert ai_analyzer.safe_event({'type': private, 'usage': {'input_tokens': -1, 'output_tokens': True}}) == {
        'type': 'other', 'item_type': None, 'usage': {}}
