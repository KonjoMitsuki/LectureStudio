import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {renderFrames} from '@remotion/renderer';

export const frameName = frame => `frame_${String(frame).padStart(8, '0')}.jpeg`;

export function frameCacheKey(props, root) {
  const hash = createHash('sha256').update(JSON.stringify(props));
  const visit = directory => {
    for (const entry of fs.readdirSync(directory, {withFileTypes: true}).sort((a,b)=>a.name.localeCompare(b.name))) {
      const file = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(file);
      else if (/\.(tsx?|mjs|css)$/.test(entry.name)) hash.update(path.relative(root, file)).update(fs.readFileSync(file));
    }
  };
  visit(path.join(root, 'src'));
  for (const file of ['frame-cache.mjs', 'render.mjs', 'package-lock.json']) hash.update(fs.readFileSync(path.join(root, file)));
  return hash.digest('hex');
}

export function validFrame(file) {
  let descriptor;
  try {
    descriptor = fs.openSync(file, 'r');
    const size = fs.fstatSync(descriptor).size;
    if (size < 4) return false;
    const header = Buffer.alloc(2), end = Buffer.alloc(2);
    fs.readSync(descriptor, header, 0, 2, 0);
    fs.readSync(descriptor, end, 0, 2, size - 2);
    return header.equals(Buffer.from([255,216])) && end.equals(Buffer.from([255,217]));
  } catch {return false;} finally {if (descriptor !== undefined) fs.closeSync(descriptor);}
}

const digest = buffer => createHash('sha256').update(buffer).digest('hex');
function validCheckpoint(file) {
  try {
    const expected = fs.readFileSync(file + '.sha256', 'utf8');
    return /^[a-f0-9]{64}$/.test(expected) && validFrame(file) && digest(fs.readFileSync(file)) === expected;
  } catch {return false;}
}

/** Capture independently of FFmpeg. Atomic JPEG checkpoints survive interruptions. */
export async function renderFrameCache({frames, directory, onProgress, render = renderFrames, ...options}) {
  fs.mkdirSync(directory, {recursive: true});
  const missing = frames.filter(frame => !validCheckpoint(path.join(directory, frameName(frame))));
  const reused = frames.length - missing.length;
  let completed = reused;
  onProgress?.(completed, frames.length);
  if (missing.length) await render({...options, frames: missing, imageFormat: 'jpeg', jpegQuality: 80,
    outputDir: null, muted: true, onStart: () => {}, onFrameUpdate: () => {},
    onFrameBuffer: (buffer, frame) => {
      if (!Buffer.isBuffer(buffer)) throw new Error('Expected encoded JPEG frame');
      const file = path.join(directory, frameName(frame));
      const temporary = file + '.partial';
      fs.writeFileSync(temporary, buffer);
      if (!validFrame(temporary)) throw new Error('Invalid JPEG frame');
      fs.renameSync(temporary, file);
      fs.writeFileSync(file + '.sha256.partial', digest(buffer));
      fs.renameSync(file + '.sha256.partial', file + '.sha256');
      onProgress?.(++completed, frames.length);
    }});
  if (!frames.every(frame => validCheckpoint(path.join(directory, frameName(frame))))) throw new Error('Frame cache is incomplete');
  return {reused, rendered: missing.length};
}
