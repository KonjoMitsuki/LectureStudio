import test from 'node:test';
import assert from 'node:assert/strict';
import {storyboardElements} from '../video/src/storyboard.mjs';
import {visualRanges} from '../video/src/timeline.mjs';

const element = {id: 'n', kind: 'rect', x: 0, y: 0, width: 100, height: 100, text: '8', font_size: 40, tone: 'fg', fill: 'card', opacity: 1, align: 'center'};
const board = {intent: '拡大して追う', elements: [element], beats: [
  {at_frame: 30, duration_in_frames: 20, changes: [{target: 'n', x: 200, width: 200, font_size: 60, text: '16'}]},
  {at_frame: 40, duration_in_frames: 10, changes: [{target: 'n', x: 400, opacity: .2, text: null}]}]};

test('seeking into an interrupted move starts from the visible state and finishes remaining changes', () => {
  assert.deepEqual(storyboardElements(board, 0), [element]);
  const middle = storyboardElements(board, 40)[0];
  assert.equal(middle.x, 100);
  assert.equal(middle.width, 150);
  assert.equal(middle.font_size, 50);
  assert.equal(middle.text, '16');
  const next = storyboardElements(board, 45)[0];
  assert.equal(next.x, 250);
  assert.equal(next.width, 175);
  assert.ok(Math.abs(next.opacity - .6) < 1e-9);
  const last = storyboardElements(board, 80)[0];
  assert.equal(last.x, 400);
  assert.equal(last.width, 200);
  assert.equal(last.text, '16');
  assert.ok(Math.abs(last.opacity - .2) < 1e-9);
  assert.equal(board.elements[0].x, 0);
  assert.deepEqual(storyboardElements(board, 40), [middle]);
});

test('zero-length and same-frame changes are deterministic and preserve literal text', () => {
  const value = {elements: [element], beats: [
    {at_frame: 0, duration_in_frames: 0, changes: [{target: 'n', text: '<svg onload="bad">', x: 10}]},
    {at_frame: 0, duration_in_frames: 0, changes: [{target: 'n', x: 20}]}]};
  assert.equal(storyboardElements(value, 0)[0].text, '<svg onload="bad">');
  assert.equal(storyboardElements(value, 0)[0].x, 20);
});

test('frame cache captures every changing frame, including interrupted motion and scene offsets', () => {
  const scene = {start_frame: 100, duration_in_frames: 150, storyboard: board,
    visual: {nodes: [], items: [], rows: [], steps: []}, captions: []};
  const ranges = visualRanges({scenes: [scene]});
  const captured = new Set(ranges.flatMap(([a,b]) => Array.from({length: b-a+1}, (_,i) => a+i)));
  for (let frame = 0; frame < 149; frame++) {
    if (JSON.stringify(storyboardElements(board, frame)) !== JSON.stringify(storyboardElements(board, frame + 1))) {
      assert.ok(captured.has(100 + frame + 1), `missing changing frame ${frame + 1}`);
    }
  }
  assert.ok(!captured.has(170), 'static hold should use cached frames');
  assert.ok(captured.has(249), 'last scene frame is retained');
});
