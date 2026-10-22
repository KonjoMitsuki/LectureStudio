import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {visualRanges, frameCount, ptsExpression} from './src/timeline.mjs';
import {bundle} from '@remotion/bundler';
import {ensureBrowser, selectComposition, renderStill} from '@remotion/renderer';
import {frameCacheKey, frameName, renderFrameCache} from './frame-cache.mjs';

const root = path.dirname(fileURLToPath(import.meta.url));
const [propsFile, publicDir, output, concurrency = '2', stillFrame] = process.argv.slice(2);
if (!propsFile || !publicDir || !output) throw new Error('Usage: node render.mjs props.json publicDir output.mp4 concurrency [stillFrame]');
const inputProps = JSON.parse(fs.readFileSync(propsFile, 'utf8'));
const phase = (value) => console.log(JSON.stringify({type: 'phase', phase: value}));
phase('browser');
const installed = path.join(root, '../tools/playwright/chromium-1208/chrome-linux64/chrome');
if (!process.env.LECTURE_CHROMIUM_PATH) {
  process.env.LECTURE_CHROMIUM_PATH = fs.existsSync(installed) ? installed : (await ensureBrowser({chromeMode: 'headless-shell'})).path;
}
const browserExecutable = path.join(root, '../scripts/chromium_sandbox.py');
const chromeMode = process.env.LECTURE_CHROMIUM_PATH.includes('headless') ? 'headless-shell' : 'chrome-for-testing';
phase('bundle');
const serveUrl = await bundle({entryPoint: path.join(root, 'src/index.ts'), publicDir: path.resolve(publicDir)});
phase('composition');
const composition = await selectComposition({serveUrl, id: 'Lecture', inputProps, browserExecutable, chromeMode});
if (stillFrame !== undefined) {
  await renderStill({composition, serveUrl, inputProps, browserExecutable, chromeMode, output: path.resolve(output), frame: Number(stillFrame)});
} else {
  const ranges = visualRanges(inputProps);
  const selected = frameCount(ranges);
  const totalFrames = inputProps.duration_in_frames;
  const cacheKey = frameCacheKey(inputProps, root);
  const frameDirectory = path.join(path.dirname(path.resolve(output)), 'frame_cache', cacheKey);
  const frames = ranges.flatMap(([start, end]) => Array.from({length: end - start + 1}, (_, i) => start + i));
  const totalWork = selected + totalFrames;
  let last = -1;
  let lastEmission = 0;
  const emit = (work) => {
    const progress = Math.min(1, work / totalWork);
    const value = Math.floor(progress * 100);
    if (value !== last || Date.now() - lastEmission >= 3000) {
      last = value; lastEmission = Date.now(); console.log(JSON.stringify({type: 'progress', progress}));
    }
  };
  phase('frames');
  const cached = await renderFrameCache({composition, serveUrl, inputProps, browserExecutable, chromeMode,
    directory: frameDirectory, frames, concurrency: Number(concurrency),
    onProgress: completed => emit(completed)});
  fs.writeFileSync(path.join(path.dirname(output), 'frame_cache.json'), JSON.stringify({key: cacheKey,
    total_frames: frames.length, reused_frames: cached.reused, rendered_frames: cached.rendered}, null, 2));
  const manifest = path.join(frameDirectory, 'frames.ffconcat');
  fs.writeFileSync(manifest, 'ffconcat version 1.0\n' + frames.map(frame => 'file ' + frameName(frame)).join('\n') + '\n');
  // Restore exact original timestamps, then duplicate only static frames at 30fps.
  const args = ['-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '1', '-i', manifest];
  const filters = ["[0:v]settb=1/30,setpts='" + ptsExpression(ranges) + "',fps=30,scale=out_range=tv,setrange=tv[v]"];
  inputProps.scenes.forEach((scene, i) => {
    if (!/^scene_[0-9]{3,6}\.wav$/.test(scene.audio_src)) throw new Error('Invalid audio asset');
    args.push('-i', path.join(publicDir, scene.audio_src));
    filters.push('[' + (i + 1) + ':a]apad=whole_dur=' + (scene.duration_in_frames / 30)
      + ',atrim=duration=' + (scene.duration_in_frames / 30) + ',asetpts=PTS-STARTPTS[a' + i + ']');
  });
  filters.push(inputProps.scenes.map((_, i) => '[a' + i + ']').join('') + 'concat=n=' + inputProps.scenes.length + ':v=0:a=1[a]');
  let videoLabel = 'v';
  let clipIndex = 1 + inputProps.scenes.length;
  for (const scene of inputProps.scenes) {
    if (!scene.manim_src) continue;
    if (!/^scene_[0-9]{3,6}\.mp4$/.test(scene.manim_src)) throw new Error('Invalid Manim asset');
    args.push('-i', path.join(publicDir, scene.manim_src));
    const start = scene.start_frame / 30;
    const end = (scene.start_frame + scene.duration_in_frames) / 30;
    const label = 'overlay' + clipIndex;
    filters.push(`[${clipIndex}:v]setpts=PTS-STARTPTS+${start}/TB,scale=out_range=tv,setrange=tv[clip${clipIndex}]`);
    filters.push(`[${videoLabel}][clip${clipIndex}]overlay=x=112:y=300:eof_action=pass:enable='gte(t,${start})*lt(t,${end})'[${label}]`);
    videoLabel = label;
    clipIndex++;
  }
  args.push('-filter_complex', filters.join(';'), '-map', `[${videoLabel}]`, '-map', '[a]',
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-pix_fmt', 'yuv420p', '-r', '30',
    '-c:a', 'aac', '-b:a', '192k', '-t', String(totalFrames / 30), '-movflags', '+faststart',
    '-progress', 'pipe:1', '-nostats', path.resolve(output));
  fs.writeFileSync(path.join(path.dirname(output), 'video_timeline.json'), JSON.stringify({ranges, selected_frames: selected, output_frames: totalFrames}, null, 2));
  phase('encode');
  await new Promise((resolve, reject) => {
    const process = spawn('ffmpeg', args, {stdio: ['ignore', 'pipe', 'pipe']});
    let error = '', buffer = '';
    process.stdout.on('data', chunk => {
      buffer += chunk.toString();
      const lines = buffer.split('\n'); buffer = lines.pop();
      for (const line of lines) if (line.startsWith('frame=')) emit(selected + Number(line.slice(6)));
    });
    process.stderr.on('data', chunk => {error = (error + chunk.toString()).slice(-4000);});
    process.on('error', reject);
    process.on('exit', code => code === 0 ? resolve() : reject(new Error('FFmpeg failed: ' + error)));
  });
  emit(totalWork);
}
console.log(JSON.stringify({type: 'complete', output}));
