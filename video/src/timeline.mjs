export function captionAt(captions, frame) {
  return captions?.find(caption => frame >= caption.start_frame && frame < caption.end_frame);
}

export function thinkingRemaining(scene, frame) {
  if (scene.kind !== 'quiz' || !scene.thinking_seconds || frame < scene.thinking_start_frame) return 0;
  return Math.max(0, Math.ceil((scene.thinking_start_frame + scene.thinking_seconds * 30 - frame) / 30));
}

export function stepFrame(visual, duration, index) {
  return visual.steps[index]?.at_frame ?? Math.ceil(index * Math.max(30, duration / Math.max(1, visual.steps.length)));
}

export function revealFrame(visual, duration, target, fallback) {
  const index = visual.steps.findIndex(step => step.action === 'reveal' && step.target === target);
  return index < 0 ? fallback : stepFrame(visual, duration, index);
}

/** Exact changing-frame intervals for our finite, frame-driven diagram components. */
export function visualRanges(props) {
  const ranges = [];
  for (const scene of props.scenes) {
    const visual = scene.visual;
    const duration = scene.duration_in_frames;
    const count = Math.max(visual.nodes.length, visual.items.length, visual.rows.length, 1);
    const spacing = Math.max(20, Math.min(60, Math.floor(duration * 0.35 / count)));
    const offset = scene.start_frame;
    const interval = (start, end = start) => {
      if (start < duration) ranges.push([offset + start, offset + Math.min(duration - 1, end)]);
    };
    interval(0, 12); // Scene header/footer opening fade.
    if (!scene.animation) {
      // Match each component's actual reveal time, including narration overrides.
      // Static gaps between entrances require no browser frame captures.
      if (['flowchart', 'state_diagram', 'block_diagram', 'network'].includes(visual.type)) {
        visual.nodes.forEach((node, i) => {
          const start = revealFrame(visual, duration, node.id, i * spacing);
          interval(start, start + 20);
        });
        visual.edges.forEach((edge, i) => {
          const start = revealFrame(visual, duration, edge.id, 10 + i * spacing);
          interval(start, start + 20);
        });
      } else if (['timeline', 'keywords', 'comparison'].includes(visual.type)) {
        const entries = visual.type === 'comparison' ? visual.rows : visual.items;
        entries.forEach((_, i) => {
          const start = revealFrame(visual, duration, String(i), i * spacing);
          interval(start, start + 20);
        });
      } else interval(0, 20); // Formula opening fade.
    }
    for (const state of scene.animation?.states ?? []) {
      if (state.at_frame < duration) ranges.push([offset + state.at_frame, offset + state.at_frame]);
    }
    for (let i = 0; i < visual.steps.length; i++) {
      const frame = stepFrame(visual, duration, i);
      if (frame < duration) ranges.push([offset + frame, offset + Math.min(duration - 1, frame + (visual.steps[i].action === "reveal" ? 20 : 0))]);
    }
    for (const caption of scene.captions ?? []) {
      for (const frame of [caption.start_frame, caption.end_frame]) {
        if (frame >= 0 && frame < duration) ranges.push([offset + frame, offset + frame]);
      }
    }
    if (scene.kind === 'quiz' && scene.thinking_seconds) {
      for (let i = 0; i <= scene.thinking_seconds; i++) {
        const frame = scene.thinking_start_frame + i * 30;
        if (frame >= 0 && frame < duration) ranges.push([offset + frame, offset + frame]);
      }
    }
    ranges.push([offset + Math.max(0, duration - 10), offset + duration - 1]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const range of ranges) {
    const previous = merged.at(-1);
    if (previous && range[0] <= previous[1] + 1) previous[1] = Math.max(previous[1], range[1]);
    else merged.push([...range]);
  }
  return merged;
}

export function frameCount(ranges) {
  return ranges.reduce((sum, [start, end]) => sum + end - start + 1, 0);
}

export function ptsExpression(ranges) {
  let cumulative = 0;
  const entries = ranges.map(([start, end]) => {
    const item = {offset: start - cumulative, end: cumulative + end - start + 1};
    cumulative = item.end; return item;
  });
  // A balanced expression avoids FFmpeg's parser nesting limit on long lectures.
  const expression = (start, end) => {
    if (end - start === 1) return 'N+' + entries[start].offset;
    const middle = Math.floor((start + end) / 2);
    return 'if(lt(N,' + entries[middle - 1].end + '),'
      + expression(start, middle) + ',' + expression(middle, end) + ')';
  };
  return '(' + expression(0, entries.length) + ')/(30*TB)';
}
