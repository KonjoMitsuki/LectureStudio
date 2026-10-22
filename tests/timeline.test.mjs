import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {visualRanges, frameCount, ptsExpression, revealFrame, stepFrame, captionAt, thinkingRemaining} from '../video/src/timeline.mjs';

test('static holds preserve original frame indices and every highlight boundary', () => {
  const scene = {start_frame: 0, duration_in_frames: 900, visual: {type: 'keywords', nodes: [], edges: [], rows: [], items: ['a','b','c'], steps: [{target:'0'}, {target:'1'}, {target:'2'}]}};
  const ranges = visualRanges({scenes: [scene]});
  assert.deepEqual(ranges, [[0,20],[60,80],[120,140],[300,300],[600,600],[890,899]]);
  assert.equal(frameCount(ranges), 75);
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

test('fallback animation retains each state switch during static frame optimization', () => {
  const scene = {start_frame: 120, duration_in_frames: 900,
    animation: {states: [{at_frame: 0}, {at_frame: 345}, {at_frame: 611}]},
    visual: {type: 'keywords', nodes: [], edges: [], rows: [], items: ['input'], steps: []}};
  const ranges = visualRanges({scenes: [scene]});
  for (const frame of [465, 731]) assert.ok(ranges.some(([a, b]) => a <= frame && frame <= b));
});

test('long lectures use bounded expression depth and preserve thousands of timestamps', () => {
  const ranges = Array.from({length: 3000}, (_, i) => [i * 30, i * 30 + 2]);
  const expression = ptsExpression(ranges).replaceAll('if(', 'choose(');
  const evaluate = new Function('N', 'TB', 'lt', 'choose', 'return ' + expression);
  for (const n of [0, 299, 5010, 8999]) {
    const expected = Math.floor(n / 3) * 30 + n % 3;
    assert.equal(evaluate(n, 1/30, (a,b)=>a<b, (c,a,b)=>c?a:b), expected);
  }
  let depth = 0, maximum = 0;
  for (const char of expression) {if (char === '(') maximum = Math.max(maximum, ++depth); else if (char === ')') depth--;}
  assert.ok(maximum < 20);
});

test('narration-controlled reveals preserve motion while skipping early static gaps', () => {
  const scene = {start_frame: 0, duration_in_frames: 900, visual: {type: 'flowchart',
    nodes: [{id:'a'}, {id:'b'}], edges: [{id:'ab'}], items: [], rows: [], steps: [
      {action:'reveal',target:'a',at_frame:300}, {action:'reveal',target:'b',at_frame:600},
      {action:'reveal',target:'ab',at_frame:700}]}};
  const ranges = visualRanges({scenes:[scene]});
  for (const start of [300,600,700]) for(let frame=start;frame<=start+20;frame++) {
    assert.ok(ranges.some(([a,b])=>a<=frame && frame<=b));
  }
  assert.ok(!ranges.some(([a,b])=>a<=100 && 100<=b));
  assert.ok(frameCount(ranges)<100);
});


test('real FFmpeg restores exact state boundaries after static frames are omitted', () => {
  const directory = mkdtempSync(path.join(tmpdir(), 'lecture-timeline-'));
  try {
    const selected = path.join(directory, 'selected.nut');
    execFileSync('ffmpeg', ['-y', '-hide_banner', '-loglevel', 'error',
      '-f', 'lavfi', '-i', 'color=c=red:s=16x16:r=30:d=1',
      '-f', 'lavfi', '-i', 'color=c=lime:s=16x16:r=30:d=1',
      '-f', 'lavfi', '-i', 'color=c=blue:s=16x16:r=30:d=1',
      '-filter_complex', "[0:v][1:v][2:v]concat=n=3:v=1:a=0,select='eq(n,0)+eq(n,30)+eq(n,60)+eq(n,89)',setpts=N/(30*TB)[v]",
      '-map', '[v]', '-c:v', 'ffv1', selected], {timeout:10000});
    const expression = ptsExpression([[0,0],[30,30],[60,60],[89,89]]);
    const frames = execFileSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-i', selected,
      '-vf', "setpts='" + expression + "',fps=30", '-t', '3', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'], {timeout:10000});
    const stride = 16 * 16 * 3;
    assert.equal(frames.length, 90 * stride);
    for (const [frame, channel] of [[0,0],[29,0],[30,1],[59,1],[60,2],[89,2]]) {
      for (let i=0;i<3;i++) assert.ok(i===channel ? frames[frame*stride+i]>240 : frames[frame*stride+i]<10);
    }
  } finally {rmSync(directory, {recursive:true, force:true});}
});
