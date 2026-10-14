import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {selectComposition, renderStill} from '@remotion/renderer';

const videoRoot = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(videoRoot, '..');
const directory = path.join(projectRoot, 'data/diagram-gallery');
fs.mkdirSync(directory, {recursive: true});
const types = ['flowchart', 'state_diagram', 'block_diagram', 'network', 'timeline', 'comparison', 'formula', 'keywords'];
const titles = ['処理を順番に進める', '状態が切り替わる', '構成要素を理解する', '情報が届く仕組み', '時間の流れをたどる', '違いを比較する', '計算の過程を見る', 'キーワードを整理する'];
const scenes = types.map((type, i) => ({id: `scene_00${i + 1}`, title: titles[i], narration: '', concepts: ['図解部品の検証'], source_pages: [1], supplemental: true,
  audio_src: '', audio_seconds: 2, duration_in_frames: 90, start_frame: i * 90,
  captions: [{text: '説明に合わせて、図の関係と具体例を順番に確認します。', start_frame: 0, end_frame: 80}],
  visual: {type, nodes: [{id: 'a', label: '入力'}, {id: 'b', label: '処理'}, {id: 'c', label: '出力'}],
    edges: [{id: 'ab', source: 'a', target: 'b', label: '送る'}, {id: 'bc', source: 'b', target: 'c', label: '返す'}],
    items: ['目的を確認する', '仕組みを説明する', '具体例で理解する', '要点を復習する'],
    columns: ['観点', '線形探索', '二分探索'], rows: [['前提条件', '整列は不要', '整列が必要'], ['計算量', 'O(n)', 'O(log n)']],
    formula: 'T(n)=\\log_2 n\\quad (n=1024\\Rightarrow 10)', steps: [{action: 'highlight_node', target: 'a'}]}}));
const quiz = {id: 'scene_009', title: '整列せずに使える探索は？', narration: '', concepts: ['探索の前提条件'], source_pages: [1], supplemental: true,
  kind: 'quiz', thinking_seconds: 5, thinking_start_frame: 90, audio_src: '', audio_seconds: 2.5,
  duration_in_frames: 240, start_frame: scenes.length * 90,
  captions: [{text: '整列せずに使える探索を選びましょう。少し考えてみましょう。', start_frame: 0, end_frame: 80}],
  visual: {type: 'keywords', nodes: [], edges: [], items: ['A：線形探索', 'B：二分探索'], columns: [], rows: [], formula: '', steps: []}};
scenes.push(quiz);
const answer = {...quiz, id: 'scene_010', title: '正答：A 線形探索', kind: 'quiz_answer', thinking_seconds: 0, duration_in_frames: 90, start_frame: quiz.start_frame + quiz.duration_in_frames,
  captions: [{text: '先頭から順に比較するので、整列されていなくても探索できます。', start_frame: 0, end_frame: 80}],
  visual: {...quiz.visual, type: 'comparison', items: [], columns: ['線形探索', '二分探索'], rows: [['整列が不要', '整列が必要']]}};
scenes.push(answer);
const props = {title: '図解検証', scenes, style: 'motion', duration_in_frames: answer.start_frame + answer.duration_in_frames};
process.env.LECTURE_CHROMIUM_PATH ||= path.join(projectRoot, 'tools/playwright/chromium-1208/chrome-linux64/chrome');
const browserExecutable = path.join(projectRoot, 'scripts/chromium_sandbox.py');
const serveUrl = await bundle({entryPoint: path.join(videoRoot, 'src/index.ts')});
const composition = await selectComposition({serveUrl, id: 'Lecture', inputProps: props, browserExecutable, chromeMode: 'chrome-for-testing'});
for (const [i, type] of types.entries()) {
  await renderStill({serveUrl, composition, inputProps: props, output: path.join(directory, `${type}.png`), frame: i * 90 + 60,
    browserExecutable, chromeMode: 'chrome-for-testing'});
  console.log(`PASS: ${type}`);
}
for (const [name, frame] of [['quiz-question', quiz.start_frame + 60], ['quiz-thinking', quiz.start_frame + 120], ['quiz-answer', answer.start_frame + 60]]) {
  await renderStill({serveUrl, composition, inputProps: props, output: path.join(directory, `${name}.png`), frame,
    browserExecutable, chromeMode: 'chrome-for-testing'});
  console.log(`PASS: ${name}`);
}
fs.writeFileSync(path.join(directory, 'result.json'), JSON.stringify({types, count: types.length + 3, captions: true, quiz: true, rendered: true}));
