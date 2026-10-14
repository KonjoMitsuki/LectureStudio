import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {visualRanges, frameCount, ptsExpression} from './src/timeline.mjs';
import {bundle} from '@remotion/bundler';
import {ensureBrowser, selectComposition, renderMedia, renderStill} from '@remotion/renderer';

const root = path.dirname(fileURLToPath(import.meta.url));
const [propsFile, publicDir, output, concurrency = '2', stillFrame] = process.argv.slice(2);
if (!propsFile || !publicDir || !output) throw new Error('Usage: node render.mjs props.json publicDir output.mp4 concurrency [stillFrame]');
const inputProps = JSON.parse(fs.readFileSync(propsFile, 'utf8'));
const installed = path.join(root, '../tools/playwright/chromium-1208/chrome-linux64/chrome');
if (!process.env.LECTURE_CHROMIUM_PATH) {
  process.env.LECTURE_CHROMIUM_PATH = fs.existsSync(installed) ? installed : (await ensureBrowser({chromeMode: 'headless-shell'})).path;
}
const browserExecutable = path.join(root, '../scripts/chromium_sandbox.py');
const chromeMode = process.env.LECTURE_CHROMIUM_PATH.includes('headless') ? 'headless-shell' : 'chrome-for-testing';
const serveUrl = await bundle({entryPoint: path.join(root, 'src/index.ts'), publicDir: path.resolve(publicDir)});
const composition = await selectComposition({serveUrl, id: 'Lecture', inputProps, browserExecutable, chromeMode});
if (stillFrame !== undefined) {
  await renderStill({composition, serveUrl, inputProps, browserExecutable, chromeMode, output: path.resolve(output), frame: Number(stillFrame)});
} else {
  const ranges = visualRanges(inputProps);
  const selected = frameCount(ranges);
  const totalFrames = inputProps.duration_in_frames;
  const intermediate = path.resolve(output + '.frames.mp4');
  const totalWork = selected + totalFrames;
  let last = -1;
  const emit = (work) => {
    const progress = Math.min(1, work / totalWork);
    const value = Math.floor(progress * 100);
    if (value !== last) {last = value; console.log(JSON.stringify({type: 'progress', progress}));}
  };
  await renderMedia({composition, serveUrl, inputProps, browserExecutable, chromeMode,
    codec: 'h264', audioCodec: 'aac', pixelFormat: 'yuv420p', crf: 22, x264Preset: 'veryfast',
    outputLocation: intermediate, frameRange: ranges, muted: true,
    concurrency: Number(concurrency), disableSharedMemoryCapture: true,
    onProgress: ({renderedFrames}) => emit(renderedFrames)});
  // Restore exact original timestamps, then duplicate only static frames at 30fps.
  const args = ['-y', '-hide_banner', '-loglevel', 'error', '-i', intermediate];
  const filters = ["[0:v]setpts='" + ptsExpression(ranges) + "',fps=30[v]"];
  inputProps.scenes.forEach((scene, i) => {
    if (!/^scene_[0-9]{3}\.wav$/.test(scene.audio_src)) throw new Error('Invalid audio asset');
    args.push('-i', path.join(publicDir, scene.audio_src));
    filters.push('[' + (i + 1) + ':a]apad=whole_dur=' + (scene.duration_in_frames / 30)
      + ',atrim=duration=' + (scene.duration_in_frames / 30) + ',asetpts=PTS-STARTPTS[a' + i + ']');
  });
  filters.push(inputProps.scenes.map((_, i) => '[a' + i + ']').join('') + 'concat=n=' + inputProps.scenes.length + ':v=0:a=1[a]');
  args.push('-filter_complex', filters.join(';'), '-map', '[v]', '-map', '[a]',
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-pix_fmt', 'yuv420p', '-r', '30',
    '-c:a', 'aac', '-b:a', '192k', '-t', String(totalFrames / 30), '-movflags', '+faststart',
    '-progress', 'pipe:1', '-nostats', path.resolve(output));
  fs.writeFileSync(path.join(path.dirname(output), 'video_timeline.json'), JSON.stringify({ranges, selected_frames: selected, output_frames: totalFrames}, null, 2));
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
  fs.unlinkSync(intermediate);
}
console.log(JSON.stringify({type: 'complete', output}));
