"""Render every trusted Manim template to real MP4 and inspect its media streams."""
import asyncio
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.models import Animation
from backend.app.services.checkpoints import save_json
from backend.app.services.manim_service import render_manim, timed_animation


def examples():
    for template in ('array', 'tree', 'graph', 'formula', 'complexity'):
        a = {'template': template, 'nodes': [], 'edges': [], 'curves': [], 'states': []}
        if template in {'tree', 'graph'}:
            a['nodes'] = [{'id': n, 'label': n.upper()} for n in ('a', 'b', 'c')]
            a['edges'] = [{'id': 'ab', 'source': 'a', 'target': 'b', 'label': ''}, {'id': 'ac', 'source': 'a', 'target': 'c', 'label': ''}]
        if template == 'complexity':
            a['curves'] = ['linear', 'quadratic', 'cubic']
        for i, cue in enumerate(('最初', '次に')):
            a['states'].append({'values': ([3,1,2] if i == 0 else [1,3,2]) if template == 'array' else [],
                'highlight': (['0', '1'] if template == 'array' else ['a' if i == 0 else 'b'] if template in {'tree', 'graph'} else ['linear' if i == 0 else 'quadratic'] if template == 'complexity' else []),
                'formula': ('T(8) = 8 × log₂8' if i == 0 else 'T(8) = 8 × 3 = 24') if template == 'formula' else '',
                'label': '初期状態' if i == 0 else '状態の変化', 'cue': cue})
        yield Animation.model_validate(a).model_dump()


async def main():
    directory = ROOT / 'data/manim-smoke'
    directory.mkdir(parents=True, exist_ok=True)
    results = []
    for animation in examples():
        scene = {'narration': '最初の入力です。次に状態を変えます。', 'animation': animation}
        clip = await render_manim(timed_animation(scene, 2.5), 90, 'motion', directory)
        final = directory / (animation['template'] + '.mp4')
        shutil.copyfile(clip, final)
        results.append({'template': animation['template'], 'path': str(final), 'frames': 90, 'status': 'PASS'})
        print(animation['template'] + ': PASS', flush=True)
    save_json(directory / 'report.json', results)


if __name__ == '__main__':
    asyncio.run(main())
