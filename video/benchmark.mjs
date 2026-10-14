import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {selectComposition, renderMedia} from '@remotion/renderer';
const root = path.dirname(fileURLToPath(import.meta.url));
const props = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const publicDir = path.resolve(process.argv[3]);
const outputDir = path.resolve('../data/render-benchmark');
fs.mkdirSync(outputDir, {recursive: true});
process.env.LECTURE_CHROMIUM_PATH ||= path.resolve('../tools/playwright/chromium-1208/chrome-linux64/chrome');
const browserExecutable = path.resolve('../scripts/chromium_sandbox.py');
const serveUrl = await bundle({entryPoint: path.join(root, 'src/index.ts'), publicDir});
const composition = await selectComposition({serveUrl, id: 'Lecture', inputProps: props, browserExecutable, chromeMode: 'chrome-for-testing'});
const results = [];
for (const mode of ['0', '1']) {
  process.env.LECTURE_BROWSER_USE_SHM = mode;
  const start = performance.now();
  await renderMedia({serveUrl, composition, inputProps: props, browserExecutable, chromeMode: 'chrome-for-testing',
    frameRange: [0, 89], codec: 'h264', audioCodec: 'aac', concurrency: 2, disableSharedMemoryCapture: true,
    outputLocation: path.join(outputDir, `shm-${mode}.mp4`), x264Preset: 'veryfast'});
  const result = {shared_memory: mode === '1', frames: 90, seconds: (performance.now() - start) / 1000};
  results.push(result); console.log(JSON.stringify(result));
}
fs.writeFileSync(path.join(outputDir, 'result.json'), JSON.stringify(results, null, 2));
