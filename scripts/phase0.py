"""Real-service PDF → Codex → VOICEVOX → Remotion acceptance gate."""
import asyncio
import json
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.config import settings
from backend.app.models import GenerationSettings, validate_lecture
from backend.app.services.pdf_parser import parse_pdf
from backend.app.services.ai_analyzer import CodexCLIAnalyzer
from backend.app.services.voicevox import Voicevox
from backend.app.services.render_service import render_video
from backend.app.services.coverage import validate_content_plan, validate_coverage
from backend.app.services.checkpoints import GENERATION_VERSION


async def main():
    workdir = settings.data_dir / "phase0"
    workdir.mkdir(parents=True, exist_ok=True)
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests/fixtures/search_algorithms.pdf"
    document = await asyncio.to_thread(parse_pdf, pdf, workdir / "pages")
    (workdir / "document.json").write_text(json.dumps(document, ensure_ascii=False, indent=2))
    print(f"PDF: {document['page_count']} pages; embedded images: {sum(len(p['images']) for p in document['pages'])}", flush=True)
    options = GenerationSettings(duration="test")
    script = workdir / "lecture.json"
    fingerprint = hashlib.sha256(pdf.read_bytes() + json.dumps([GENERATION_VERSION, options.model_dump(),
        *[(ROOT / f'prompts/{name}.txt').read_text() for name in ('plan', 'analyze')]], sort_keys=True).encode()).hexdigest()
    fingerprint_path = workdir / "source.sha256"
    if script.exists() and fingerprint_path.exists() and fingerprint_path.read_text() == fingerprint:
        lecture = validate_lecture(json.loads(script.read_text()), [p["number"] for p in document["pages"]])
    else:
        lecture = await CodexCLIAnalyzer().analyze(document, options, workdir / "ai")
        script.write_text(lecture.model_dump_json(indent=2))
        fingerprint_path.write_text(fingerprint)
    validate_coverage(lecture, validate_content_plan(json.loads((workdir / 'ai/content_plan.json').read_text()), document))
    print(f"AI: {len(lecture.scenes)} scenes; {len(lecture.coverage)} topics covered", flush=True)
    audio = []
    for scene in lecture.scenes:
        audio.append(await Voicevox().synthesize(scene.narration, options.speaker, options.speed, settings.data_dir / "audio"))
        print(f"VOICEVOX: {scene.id}, {audio[-1]['audio_seconds']:.2f}s", flush=True)
    (workdir / "audio.json").write_text(json.dumps(audio, indent=2))
    result = await render_video(lecture.model_dump(), audio, options.style, workdir,
        lambda value: print(f"Remotion: {round(value * 100)}%", flush=True))
    (workdir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"PASS: {result['path']} ({result['seconds']:.2f}s)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
