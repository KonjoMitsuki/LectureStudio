"""Real PDF -> Codex -> VOICEVOX -> hybrid MP4, with no video duration ceiling.

Run against an existing local lecture PDF in an isolated validation directory.
A repeat invocation resumes only matching source/settings and validated checkpoints.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.models import GenerationSettings, validate_lecture
from backend.app.services.checkpoints import save_json
from backend.app.services.coverage import validate_content_plan, validate_coverage
from backend.app.services.pipeline import Pipeline
from backend.app.services.render_service import inspect_video
from backend.app.storage import Store


async def validate(pdf: Path, output: Path, require_manim: bool = False):
    options = GenerationSettings(duration='test')
    key = hashlib.sha256(pdf.read_bytes()).hexdigest()
    store = Store(output)
    marker = output / 'acceptance_project.json'
    prior = json.loads(marker.read_text()) if marker.exists() else {}
    row = store.get(prior.get('project_id', '')) if prior.get('source_sha256') == key else None
    if row is None:
        row = store.create('lecture.pdf', options.model_dump())
        directory = store.directory(row['id'])
        directory.mkdir(parents=True)
        (directory / 'source.pdf').write_bytes(pdf.read_bytes())
        save_json(marker, {'project_id': row['id'], 'source_sha256': key})
    directory = store.directory(row['id'])
    # This CLI owns this isolated validation run. Do not recover unrelated app jobs.
    store.recover()
    job = store.enqueue(row['id'], options.model_dump(), 10)
    pipeline = Pipeline(store)
    task = asyncio.create_task(pipeline.run(row['id'], job))
    last = None
    while not task.done():
        state = store.activity(row['id']) or {}
        if state.get('job_id') != job:
            state = {}
        ai = state.get('ai') or {}
        snapshot = (state.get('stage'), state.get('task'), ai.get('completed'), ai.get('total'))
        if snapshot != last:
            print(json.dumps({'stage': snapshot[0], 'task': snapshot[1], 'completed': snapshot[2], 'total': snapshot[3]}, ensure_ascii=False), flush=True)
            last = snapshot
        await asyncio.wait({task}, timeout=2)
    await task
    row = store.get(row['id'])
    if row['status'] != 'completed':
        raise RuntimeError(row.get('error') or 'Validation pipeline failed')
    document = json.loads((directory / 'document.json').read_text())
    plan = validate_content_plan(json.loads((directory / 'ai/content_plan.json').read_text()), document)
    lecture = validate_lecture(json.loads((directory / 'lecture.json').read_text()), [p['number'] for p in document['pages']])
    validate_coverage(lecture, plan)
    report = json.loads((directory / 'render_report.json').read_text())
    manim = sum(item['actual'] == 'manim' for item in report)
    if require_manim and not manim:
        raise RuntimeError('No actual Manim scene rendered; --require-manim acceptance failed')
    metadata = await inspect_video(directory / 'video.mp4')
    result = {'status': 'PASS', 'pages': document['page_count'], 'topics': len(plan.topics),
        'covered_topics': len(lecture.coverage), 'scenes': len(lecture.scenes), 'manim_scenes': manim,
        'fallback_scenes': sum(bool(item['fallback_reason']) for item in report),
        'seconds': float(metadata['format']['duration']), 'video': str(directory / 'video.mp4'),
        'limits': ['Coverage verifies references and verbatim explanations, not semantic correctness.',
            'Cue timing uses text position and WAV duration, not forced alignment.',
            'Embedded PDF images are not interpreted by the analyzer.']}
    save_json(output / 'acceptance_report.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/acceptance')
    parser.add_argument('--require-manim', action='store_true')
    args = parser.parse_args()
    asyncio.run(validate(args.pdf.resolve(), args.output.resolve(), args.require_manim))
