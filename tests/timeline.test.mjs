import test from 'node:test';
import assert from 'node:assert/strict';
import {visualRanges, frameCount, ptsExpression} from '../video/src/timeline.mjs';

test('static holds preserve original frame indices and every highlight boundary', () => {
  const scene = {start_frame: 0, duration_in_frames: 900, visual: {type: 'keywords', nodes: [], edges: [], rows: [], items: ['a','b','c'], steps: [{target:'0'}, {target:'1'}, {target:'2'}]}};
  const ranges = visualRanges({scenes: [scene]});
  assert.deepEqual(ranges, [[0,140],[300,300],[600,600],[890,899]]);
  assert.equal(frameCount(ranges), 153);
  // Evaluate only our generated numeric expression, using FFmpeg's lt/if semantics.
  const expression = ptsExpression(ranges).replaceAll('if(', 'choose(');
  const evaluate = new Function('N', 'TB', 'lt', 'choose', 'return ' + expression);
  const original = ranges.flatMap(([a,b]) => Array.from({length:b-a+1}, (_,i)=>a+i));
  for (let n=0; n<original.length; n++) assert.equal(evaluate(n, 1/30, (a,b)=>a<b, (c,a,b)=>c?a:b), original[n]);
});

test('short scenes merge overlapping intervals and preserve the final frame', () => {
  const scene = {start_frame: 0, duration_in_frames: 30, visual: {type: 'flowchart', nodes: ['a','b','c'], edges: ['ab','bc'], items: [], rows: [], steps: []}};
  assert.deepEqual(visualRanges({scenes: [scene]}), [[0,29]]);
});
