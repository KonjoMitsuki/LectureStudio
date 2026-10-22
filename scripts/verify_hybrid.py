"""Real VOICEVOX + Manim + Remotion integration with media and region checks."""
import asyncio
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.models import validate_lecture
from backend.app.config import settings
from backend.app.services.checkpoints import save_json
from backend.app.services.render_service import render_video
from backend.app.services.voicevox import Voicevox
from scripts.verify_manim import examples


async def main(force_fallback=False):
    directory = ROOT / ('data/hybrid-fallback' if force_fallback else 'data/hybrid-smoke')
    directory.mkdir(parents=True, exist_ok=True)
    if force_fallback:
        settings.manim_python = str(directory / 'missing-manim-python')
    visual = {'type': 'keywords', 'nodes': [], 'edges': [], 'items': ['入力', '状態変化'],
        'columns': [], 'rows': [], 'formula': '', 'steps': []}
    initial = {'id': 'scene_001', 'title': '配列の入替えを追う', 'narration': '最初は三、一、二の順に並んでいます。次に、三と一を入れ替えると、一、三、二になります。',
        'concepts': ['配列', '入替え'], 'source_pages': [], 'supplemental': True, 'estimated_seconds': 10,
        'visual': visual, 'renderer': 'manim', 'animation': next(examples())}
    second = {**initial, 'id': 'scene_002', 'title': '手順を振り返る', 'renderer': 'remotion', 'animation': None,
        'narration': '配列は、値を順番に並べて保存するデータ構造です。入れ替える前と後を比べると、アルゴリズムの動きがわかります。'}
    third = {**initial, 'id': 'scene_003', 'title': '数式に値を代入する', 'animation': list(examples())[3],
        'narration': '最初に、入力の大きさを八とし、操作回数をティーと書きます。次に、八の底二の対数は三なので、八かける三は二十四です。'}
    lecture = validate_lecture({'title': '描画統合の検証', 'learning_goals': ['配列の状態変化を理解する'], 'warnings': [],
        'scenes': [initial, second, third], 'coverage': []}, []).model_dump()
    audio = [await Voicevox().synthesize(s['narration'], 3, 1, directory / 'audio') for s in lecture['scenes']]
    result = await render_video(lecture, audio, 'motion', directory)
    report = json.loads((directory / 'render_report.json').read_text())
    expected = ['remotion'] * 3 if force_fallback else ['manim', 'remotion', 'manim']
    if [s['actual'] for s in report] != expected:
        raise RuntimeError('Mixed renderer verification failed')
    if force_fallback and not all(report[i]['fallback_reason'] for i in [0, 2]):
        raise RuntimeError('Fallback reasons missing')
    save_json(directory / 'result.json', {'status': 'PASS', **result})
    print(json.dumps({'status': 'PASS', 'seconds': result['seconds'], 'video': result['path'],
        'renderers': [s['actual'] for s in report]}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--force-fallback', action='store_true')
    asyncio.run(main(parser.parse_args().force_fallback))
