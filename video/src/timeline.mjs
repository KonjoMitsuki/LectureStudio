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
    let animationEnd = 20;
    if (['flowchart', 'state_diagram', 'block_diagram', 'network'].includes(visual.type)) {
      animationEnd = Math.max(20, (visual.nodes.length - 1) * spacing + 20,
        visual.edges.length ? 10 + (visual.edges.length - 1) * spacing + 20 : 0);
    } else if (['timeline', 'keywords'].includes(visual.type)) {
      animationEnd = (visual.items.length - 1) * spacing + 20;
    } else if (visual.type === 'comparison') {
      animationEnd = (visual.rows.length - 1) * spacing + 20;
    }
    const offset = scene.start_frame;
    ranges.push([offset, offset + Math.min(duration - 1, animationEnd)]);
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
  let expression = 'N+' + entries.at(-1).offset;
  for (let i = entries.length - 2; i >= 0; i--) {
    expression = 'if(lt(N,' + entries[i].end + '),N+' + entries[i].offset + ',' + expression + ')';
  }
  return '(' + expression + ')/(30*TB)';
}
