import asyncio
import copy

import pytest

from backend.app.config import settings
from backend.app.models import GenerationSettings, Lecture
from backend.app.services.pipeline import Pipeline
from backend.app.services.diagnostics import GenerationLog
from backend.app.storage import Store


def setup(tmp_path, valid_lecture):
    scene = valid_lecture['scenes'][0]
    second, third = copy.deepcopy(scene), copy.deepcopy(scene)
    second.update(id='scene_002', narration='二番目の説明です。')
    third.update(id='scene_003')  # Same text shares one synthesis call.
    lecture = Lecture.model_validate({**valid_lecture, 'scenes': [scene, second, third]})
    store = Store(tmp_path)
    project = store.create('lecture.pdf', GenerationSettings().model_dump())
    job = store.enqueue(project['id'], project['settings'], 10)
    return lecture, store, project, GenerationLog(store, project['id'], job)


async def test_audio_concurrency_preserves_order_and_deduplicates_text(tmp_path, valid_lecture, monkeypatch):
    monkeypatch.setattr(settings, 'voice_concurrency', 2)
    lecture, store, project, log = setup(tmp_path, valid_lecture)
    class Voice:
        running = 0
        peak = 0
        calls = 0
        async def synthesize(self, text, *args):
            self.calls += 1
            self.running += 1
            self.peak = max(self.peak, self.running)
            await asyncio.sleep(.04 if text == lecture.scenes[0].narration else .01)
            self.running -= 1
            return {'path': str(tmp_path / ('first.wav' if text == lecture.scenes[0].narration else 'second.wav')), 'audio_seconds': 1, 'duration_in_frames': 45}
    voice = Voice()
    audio = await Pipeline(store, voice=voice).synthesize_scenes(lecture, GenerationSettings(), project['id'], log)
    assert voice.calls == 2 and voice.peak == 2 and voice.running == 0
    assert [item['path'].rsplit('/', 1)[-1] for item in audio] == ['first.wav', 'second.wav', 'first.wav']
    assert store.get(project['id'])['progress'] == 1


@pytest.mark.parametrize('cancel', [False, True])
async def test_audio_failure_or_cancellation_stops_all_pending_requests(tmp_path, valid_lecture, cancel):
    lecture, store, project, log = setup(tmp_path, valid_lecture)
    entered = asyncio.Event()
    class Voice:
        running = 0
        async def synthesize(self, text, *args):
            self.running += 1
            entered.set()
            try:
                if not cancel and text == lecture.scenes[1].narration:
                    await asyncio.sleep(.01)
                    raise RuntimeError('fixed failure')
                await asyncio.Event().wait()
            finally:
                self.running -= 1
    voice = Voice()
    task = asyncio.create_task(Pipeline(store, voice=voice).synthesize_scenes(lecture, GenerationSettings(), project['id'], log))
    await entered.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await task
    assert voice.running == 0
