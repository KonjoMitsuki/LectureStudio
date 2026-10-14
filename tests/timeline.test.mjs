import test from 'node:test';
import assert from 'node:assert/strict';
import {visualRanges, frameCount, ptsExpression, revealFrame, stepFrame, captionAt, thinkingRemaining} from '../video/src/timeline.mjs';

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

test('narration cues retain late reveals and their full animation during static holds', () => {
  const scene = {start_frame: 90, duration_in_frames: 900, visual: {type: 'comparison', nodes: [], edges: [], items: [], rows: [['a'], ['b']], steps: [{action: 'reveal', target: '1', at_frame: 450}, {action: 'highlight_item', target: '1', at_frame: 720}]}};
  const ranges = visualRanges({scenes: [scene]});
  assert.ok(ranges.some(([a,b]) => a <= 540 && b >= 560));
  assert.ok(ranges.some(([a,b]) => a <= 810 && b >= 810));
});

test('cue timing controls visibility instead of automatic opening animation', () => {
  const visual = {steps: [{action: 'reveal', target: 'b', at_frame: 450}]};
  assert.equal(revealFrame(visual, 900, 'b', 60), 450);
  assert.equal(revealFrame(visual, 900, 'a', 0), 0);
  assert.equal(stepFrame({steps: [{target: 'a'}, {target: 'b'}]}, 900, 1), 450);
});

test('captions switch exactly at boundaries and clear after speech', () => {
  const captions = [{text: '問題', start_frame: 0, end_frame: 150}, {text: '考えてみましょう', start_frame: 150, end_frame: 270}];
  assert.equal(captionAt(captions, 149).text, '問題');
  assert.equal(captionAt(captions, 150).text, '考えてみましょう');
  assert.equal(captionAt(captions, 270), undefined);
  assert.equal(captionAt(undefined, 0), undefined);
});

test('optimized render preserves subtitle switches, removal and quiz countdown', () => {
  const scene = {start_frame: 90, duration_in_frames: 480, kind: 'quiz', thinking_seconds: 5, thinking_start_frame: 330,
    captions: [{text: '問い', start_frame: 0, end_frame: 180}, {text: '考えよう', start_frame: 180, end_frame: 315}],
    visual: {type: 'keywords', nodes: [], edges: [], rows: [], items: ['選択肢'], steps: []}};
  const ranges = visualRanges({scenes: [scene]});
  for (const boundary of [180, 315, 330, 360, 390, 420, 450]) {
    assert.ok(ranges.some(([a,b]) => a <= boundary + 90 && b >= boundary + 90));
  }
  assert.equal(thinkingRemaining(scene, 329), 0);
  assert.equal(thinkingRemaining(scene, 330), 5);
  assert.equal(thinkingRemaining(scene, 359), 5);
  assert.equal(thinkingRemaining(scene, 360), 4);
  assert.equal(thinkingRemaining(scene, 480), 0);
});
