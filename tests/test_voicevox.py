import io
import wave
from pathlib import Path
import httpx
from backend.app.services.voicevox import Voicevox


async def test_voicevox_api_speed_cache_and_actual_timeline(tmp_path, monkeypatch):
    calls = []
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
        wav.writeframes(b'\x01\x01' * 30123)

    def handle(request):
        calls.append(request)
        if request.url.path == '/version':
            return httpx.Response(200, json='0.25.2')
        if request.url.path == '/audio_query':
            assert request.url.params['speaker'] == '3'
            assert request.url.params['text'] == '日本語ナレーション'
            return httpx.Response(200, json={'speedScale': 1.0})
        if request.url.path == '/synthesis':
            import json
            query = json.loads(request.content)
            assert query['speedScale'] == 1.2
            assert query['outputSamplingRate'] == 24000
            return httpx.Response(200, content=stream.getvalue())
        return httpx.Response(404)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)))
    client = Voicevox()
    first = await client.synthesize('日本語ナレーション', 3, 1.2, tmp_path)
    second = await client.synthesize('日本語ナレーション', 3, 1.2, tmp_path)
    assert first == second and first['audio_seconds'] == 30123 / 24000
    assert first['duration_in_frames'] / 30 >= first['audio_seconds'] + 0.5
    assert sum(request.url.path == '/synthesis' for request in calls) == 1
    Path(first['path']).write_bytes(b'corrupt')
    third = await client.synthesize('日本語ナレーション', 3, 1.2, tmp_path)
    assert third == first
    assert sum(request.url.path == '/synthesis' for request in calls) == 2
