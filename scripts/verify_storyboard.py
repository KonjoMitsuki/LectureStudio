"""Real Remotion/FFmpeg smoke test; synthetic tone, no AI or VOICEVOX required."""
import argparse
import asyncio
import json
import math
import struct
import wave
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.models import validate_lecture
from backend.app.services.render_service import render_video


def element(id, kind, x, y, width, height, text='', **extra):
    return dict(id=id, kind=kind, x=x, y=y, width=width, height=height, text=text, **extra)


def example():
    def scene(number, title, narration, board):
        return dict(id=f'scene_{number:03}', title=title, narration=narration, concepts=['二分探索'],
                    source_pages=[], supplemental=True, estimated_seconds=6, visual=None, storyboard=board)
    opening = {'intent': '大量の候補という問題から、半分に絞る発想へ視線を導く', 'elements': [
        element('question', 'text', 70, 160, 780, 240, '1024件から\nどう探す？', font_size=88, align='left'),
        element('idea', 'text', 70, 460, 780, 90, '一つずつ調べる？', font_size=48, opacity=0),
        *[element(f'candidate_{i}', 'ellipse', 1010 + i % 4 * 140, 110 + i // 4 * 140, 76, 76,
                  fill='card', tone='accent') for i in range(16)]],
        'beats': [{'cue': '一つずつ', 'changes': [{'target': 'idea', 'opacity': 1}]},
                  {'cue': '半分ずつ', 'changes': [
                      *[{'target': f'candidate_{i}', 'opacity': .15} for i in range(8)],
                      {'target': 'idea', 'text': '半分ずつ絞ってみよう', 'tone': 'accent'}]}]}
    values = [2, 4, 6, 8, 10, 12, 14, 16]
    search = {'intent': '14を探すとき、8との比較で左半分が不要になり、残りへ注目が移る', 'elements': [
        element('target', 'text', 50, 40, 600, 100, '探す値：14', font_size=64, align='left'),
        *[element(f'n{i}', 'rect', 70 + i * 195, 270, 145, 120, str(v), fill='card', font_size=56) for i, v in enumerate(values)],
        element('pointer', 'arrow', 728, 175, 0, 65, tone='accent'),
        element('reason', 'text', 400, 530, 1000, 90, '14 > 8', font_size=60, tone='accent', opacity=0)],
        'beats': [{'cue': '左の半分', 'changes': [
            *[{'target': f'n{i}', 'opacity': .12} for i in range(4)],
            {'target': 'reason', 'opacity': 1}]},
            {'cue': '残った候補', 'transition_seconds': .8, 'changes': [
                *[{'target': f'n{i}', 'opacity': 0} for i in range(4)],
                *[{'target': f'n{i}', 'x': 350 + (i - 4) * 280, 'y': 250, 'width': 210, 'height': 160, 'font_size': 80} for i in range(4, 8)],
                {'target': 'pointer', 'x': 735, 'y': 155},
                {'target': 'reason', 'text': '同じ操作を、残りの範囲で繰り返す', 'font_size': 44}]}]}
    conclusion = {'intent': '候補数の減少を空間の縮小で表し、比較回数の結論に結びつける', 'elements': [
        element('many', 'ellipse', 100, 130, 360, 360, '1024', fill='card', font_size=96),
        element('a', 'arrow', 500, 310, 200, 0, tone='accent'),
        element('half', 'ellipse', 750, 190, 240, 240, '512', fill='card', font_size=72, opacity=0),
        element('b', 'arrow', 1040, 310, 180, 0, tone='accent', opacity=0),
        element('few', 'ellipse', 1270, 240, 140, 140, '…', fill='card', font_size=72, opacity=0),
        element('result', 'text', 700, 510, 900, 100, '1024 → 最大11回の比較', font_size=60, tone='accent', opacity=0)],
        'beats': [{'cue': '512件', 'changes': [{'target': 'half', 'opacity': 1}]},
                  {'cue': '繰り返す', 'changes': [{'target': 'b', 'opacity': 1}, {'target': 'few', 'opacity': 1}]},
                  {'cue': '11回', 'changes': [{'target': 'result', 'opacity': 1}]}]}
    return validate_lecture({'title': '絵コンテ描画の検証（二分探索）', 'learning_goals': ['候補範囲の縮小を理解する'],
        'warnings': ['描画検証用の人工音です。実ナレーションではありません。'], 'scenes': [
            scene(1, '大量の候補をどう探す？', '1024件の候補があります。一つずつ調べる代わりに、半分ずつ絞れないでしょうか。', opening),
            scene(2, '候補を絞って拡大する', '整列した配列から14を探します。中央の8より大きいので、左の半分を除きます。残った候補に注目し、同じ操作を繰り返します。', search),
            scene(3, '半分ずつ減らす効果', '1024件が、512件になります。半分にする操作を繰り返すと、最大11回の比較で探索できます。', conclusion)]}, []).model_dump()


async def verify(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    lecture = example()
    (directory / 'lecture.json').write_text(json.dumps(lecture, ensure_ascii=False, indent=2))
    audio = []
    for i, _ in enumerate(lecture['scenes']):
        output = directory / f'tone_{i}.wav'
        samples = [int(1800 * math.sin(2 * math.pi * (220 + i * 55) * j / 24000)) for j in range(6 * 24000)]
        with wave.open(str(output), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(struct.pack(f'<{len(samples)}h', *samples))
        audio.append({'path': str(output), 'audio_seconds': 6, 'duration_in_frames': 195})
    result = await render_video(lecture, audio, 'motion', directory)
    (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"PASS: {result['seconds']}s, 3 composed scenes; synthetic audio only")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('work/storyboard-smoke'))
    asyncio.run(verify(parser.parse_args().output.resolve()))
