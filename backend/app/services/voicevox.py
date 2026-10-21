import hashlib
import json
import math
import wave
from pathlib import Path
import httpx
from ..config import settings
from .diagnostics import record

FPS = 30
TAIL_FRAMES = 15


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
        if audio.getnframes() == 0 or audio.getnchannels() > 2 or duration > 600:
            raise ValueError("音声ファイルの形式または長さが不正です")
        return duration


class Voicevox:
    async def speakers(self):
        async with httpx.AsyncClient(base_url=settings.voicevox_url, timeout=10, trust_env=False) as client:
            response = await client.get("/speakers")
            response.raise_for_status()
            return response.json()

    async def synthesize(self, text: str, speaker: int, speed: float, cache: Path) -> dict:
        cache.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(base_url=settings.voicevox_url, timeout=120, trust_env=False) as client:
            version = await client.get("/version")
            version.raise_for_status()
            key = hashlib.sha256(json.dumps([version.json(), text, speaker, speed], ensure_ascii=False).encode()).hexdigest()
            output = cache / f"{key}.wav"
            if output.exists():
                try:
                    seconds = wav_seconds(output)
                    record("保存済みの同じ音声を再利用できました")
                    return {"path": str(output), "audio_seconds": seconds, "duration_in_frames": max(30, math.ceil(seconds * FPS) + TAIL_FRAMES)}
                except (ValueError, wave.Error, EOFError):
                    output.unlink()
            query = await client.post("/audio_query", params={"text": text, "speaker": speaker})
            query.raise_for_status()
            payload = query.json()
            payload["speedScale"] = speed
            payload["outputSamplingRate"] = 24000
            result = await client.post("/synthesis", params={"speaker": speaker}, json=payload)
            result.raise_for_status()
            temp = output.with_suffix(".tmp.wav")
            temp.write_bytes(result.content)
            try:
                seconds = wav_seconds(temp)
                temp.replace(output)
            finally:
                temp.unlink(missing_ok=True)
            return {"path": str(output), "audio_seconds": seconds, "duration_in_frames": max(30, math.ceil(seconds * FPS) + TAIL_FRAMES)}
