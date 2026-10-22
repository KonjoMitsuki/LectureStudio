"""Trusted, finite Manim templates. No eval, exec, imports or TeX from AI data."""
import json
import math
import os
from pathlib import Path
import sys

import numpy as np
from manim import (Arrow, Circle, Line, Scene, Square, Text, Transform, VGroup, VMobject,
                   config, tempconfig)

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend.app.models import Animation
from backend.app.services.animation_layout import node_positions


def fit_text(value, color, size=34, width=11.8, height=.7):
    text = Text(str(value), font='Noto Sans CJK JP', font_size=size, color=color)
    if text.width > width:
        text.scale_to_fit_width(width)
    if text.height > height:
        text.scale_to_fit_height(height)
    return text


class LectureTemplate(Scene):
    def construct(self):
        payload = json.loads(Path(os.environ['LECTURE_MANIM_INPUT']).read_text())
        raw = payload['animation']
        base = {k: v for k, v in raw.items() if k != 'positions'}
        base['states'] = [{k: v for k, v in s.items() if k != 'at_frame'} for s in raw['states']]
        animation = Animation.model_validate(base).model_dump()
        frames = payload['frames']
        if type(frames) is not int or not 1 <= frames <= 100000:
            raise ValueError('Invalid frame count')
        times = [s['at_frame'] for s in raw['states']]
        if any(type(t) is not int or not 0 <= t < frames for t in times) or times != sorted(times) or times[0] != 0:
            raise ValueError('Invalid state timing')
        palette = payload['palette']
        fg, accent, muted = palette['fg'], palette['accent'], palette['muted']
        self.camera.background_color = palette['bg']
        positions = node_positions(animation) if animation['template'] in {'tree', 'graph'} else {}
        distances = [math.dist(a, b) for key, a in positions.items() for other, b in positions.items() if key != other]
        radius = min(.31, min(distances) * .38) if distances else .31

        def draw(state):
            highlights = set(state['highlight'])
            group = VGroup()
            template = animation['template']
            if template == 'array':
                values = state['values']
                for i, value in enumerate(values):
                    x = (i - (len(values) - 1) / 2) * 1.4
                    color = accent if str(i) in highlights else muted
                    cell = Square(side_length=1.05, color=color, fill_color=color, fill_opacity=.12).move_to([x, .25, 0])
                    number = fit_text(f'{value:g}', fg, width=.95).move_to(cell)
                    index = fit_text(str(i), muted, size=22).move_to([x, -.55, 0])
                    group.add(cell, number, index)
            elif template in {'tree', 'graph'}:
                for edge in animation['edges']:
                    start, end = np.array([*positions[edge['source']], 0]), np.array([*positions[edge['target']], 0])
                    color = accent if edge['id'] in highlights else muted
                    group.add(Arrow(start, end, buff=.29, color=color, stroke_width=3, max_tip_length_to_length_ratio=.08))
                    if edge['label']:
                        group.add(fit_text(edge['label'], fg, size=20, width=1.2, height=.25).move_to((start + end) / 2 + [0,.18,0]))
                for node in animation['nodes']:
                    point = [*positions[node['id']], 0]
                    color = accent if node['id'] in highlights else muted
                    group.add(Circle(radius=radius, color=color, fill_color=palette['bg'], fill_opacity=1).move_to(point))
                    group.add(fit_text(node['label'], fg, size=24, width=1.6, height=min(.38, radius * 1.1)).move_to(point))
            elif template == 'formula':
                # Text uses Pango. Backslashes remain literal; no TeX compiler or shell escape.
                group.add(fit_text(state['formula'], fg, size=48, height=1.5).move_to([0,.3,0]))
            else:
                origin = np.array([-4.8, -1.0, 0])
                group.add(Arrow(origin, origin + [8.5, 0, 0], buff=0, color=muted), Arrow(origin, origin + [0, 2.25, 0], buff=0, color=muted))
                group.add(fit_text('n: input size (1–4)', muted, size=20).move_to([0,-1.25,0]))
                group.add(fit_text('operations (0–64)', muted, size=20).move_to([-4,1.55,0]))
                functions = {'constant': lambda n: 1, 'log': math.log2, 'linear': lambda n: n,
                    'n_log_n': lambda n: n * math.log2(n), 'quadratic': lambda n: n*n, 'cubic': lambda n: n**3}
                labels = {'constant': 'O(1)', 'log': 'O(log n)', 'linear': 'O(n)', 'n_log_n': 'O(n log n)', 'quadratic': 'O(n²)', 'cubic': 'O(n³)'}
                colors = [accent, '#f3ae64', '#9c9eff', '#ed8ca2']
                for i, curve in enumerate(animation['curves']):
                    color = colors[i]
                    points = [origin + [(n-1)/3 * 8, functions[curve](n)/64 * 2, 0] for n in np.linspace(1,4,80)]
                    graph = VMobject(color=color, stroke_width=6 if curve in highlights else 3).set_points_as_corners(points)
                    group.add(graph, fit_text(labels[curve], color, size=23, width=2).move_to([5.1,1-i*.55,0]))
            if state['label']:
                group.add(fit_text(state['label'], fg, size=28, height=.4).move_to([0,-1.65,0]))
            return group

        current = draw(animation['states'][0])
        self.add(current)
        cursor = 0
        for i, state in enumerate(animation['states'][1:], 1):
            start = times[i]
            if start > cursor:
                self.wait((start - cursor) / 30)
                cursor = start
            end = min(frames, times[i + 1] if i + 1 < len(times) else frames)
            transition = min(12, max(0, end - cursor))
            target = draw(state)
            if transition:
                self.play(Transform(current, target), run_time=transition / 30)
                cursor += transition
            else:
                self.remove(current)
                current = target
                self.add(current)
        if cursor < frames:
            self.wait((frames - cursor) / 30)


if __name__ == '__main__':
    output = Path(sys.argv[1]).resolve()
    with tempconfig({'renderer': 'cairo', 'pixel_width': 1696, 'pixel_height': 480, 'frame_rate': 30,
        'frame_width': 14.1333333333, 'frame_height': 4, 'output_file': str(output),
        'media_dir': str(output.parent / 'media'), 'disable_caching': True, 'write_to_movie': True,
        'format': 'mp4', 'verbosity': 'ERROR', 'progress_bar': 'none'}):
        LectureTemplate().render()
