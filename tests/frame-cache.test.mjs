import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {tmpdir} from 'node:os';
import {renderFrameCache, frameName} from '../video/frame-cache.mjs';

const jpeg = Buffer.from([255,216,0,0,255,217]);
test('interrupted frame capture resumes missing frames in original coordinates', async () => {
  const directory = fs.mkdtempSync(path.join(tmpdir(), 'lecture-frame-cache-'));
  try {
    let calls = [];
    await assert.rejects(renderFrameCache({frames:[0,30,60],directory,render:async options=>{
      options.onFrameBuffer(jpeg,0);options.onFrameBuffer(jpeg,30);throw new Error('interrupted');
    }}),/interrupted/);
    const result = await renderFrameCache({frames:[0,30,60],directory,render:async options=>{
      calls.push(options.frames);options.onFrameBuffer(jpeg,60);
    }});
    assert.deepEqual(calls,[[60]]);assert.equal(result.reused,2);
    assert.ok(fs.existsSync(path.join(directory,frameName(60))));
    await renderFrameCache({frames:[0,30,60],directory,render:async()=>assert.fail('cache should be reused')});
    fs.writeFileSync(path.join(directory,frameName(30)),Buffer.from([255,216,99,0,255,217]));
    calls=[];
    await renderFrameCache({frames:[0,30,60],directory,render:async options=>{
      calls.push(options.frames);options.onFrameBuffer(jpeg,30);
    }});
    assert.deepEqual(calls,[[30]]);
  } finally {fs.rmSync(directory,{recursive:true,force:true});}
});
