"""Deterministic positions shared through validated render data, never model code."""
import math


def node_positions(animation: dict) -> dict[str, list[float]]:
    ids = [node['id'] for node in animation['nodes']]
    if animation['template'] == 'tree':
        children = {node: [] for node in ids}
        for edge in animation['edges']:
            children[edge['source']].append(edge['target'])
        root = next(n for n in ids if all(e['target'] != n for e in animation['edges']))
        levels, current = [], [root]
        while current:
            levels.append(current)
            current = [child for node in current for child in children[node]]
        return {node: [((i + 1) / (len(level) + 1) - .5) * 10, 1 - depth * 2 / max(1, len(levels) - 1)]
            for depth, level in enumerate(levels) for i, node in enumerate(level)}
    return {node: [3.9 * math.cos(2 * math.pi * i / len(ids)), 1.05 * math.sin(2 * math.pi * i / len(ids))]
        for i, node in enumerate(ids)}
