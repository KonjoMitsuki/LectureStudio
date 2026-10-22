const numbers = ['x', 'y', 'width', 'height', 'font_size', 'opacity'];
const discrete = ['text', 'tone', 'fill'];

/** Evaluate from time zero so seeks, cached captures and interrupted moves agree. */
export function storyboardElements(board, frame) {
  const states = new Map(board.elements.map(element => [element.id, {...element}]));
  const tracks = new Map();
  const sample = time => {
    for (const [id, track] of tracks) {
      const amount = track.duration <= 0 ? 1 : Math.max(0, Math.min(1, (time - track.start) / track.duration));
      const eased = amount * amount * (3 - 2 * amount);
      const state = states.get(id);
      for (const key of numbers) state[key] = track.from[key] + (track.to[key] - track.from[key]) * eased;
      for (const key of discrete) state[key] = track.to[key];
    }
  };
  for (const beat of board.beats) {
    if (beat.at_frame > frame) break;
    sample(beat.at_frame);
    for (const change of beat.changes) {
      const current = {...states.get(change.target)};
      const patch = Object.fromEntries(Object.entries(change).filter(([key, value]) => key !== 'target' && value != null));
      const destination = tracks.get(change.target)?.to ?? current;
      tracks.set(change.target, {from: current, to: {...destination, ...patch}, start: beat.at_frame, duration: beat.duration_in_frames});
    }
  }
  sample(frame);
  return [...states.values()];
}
