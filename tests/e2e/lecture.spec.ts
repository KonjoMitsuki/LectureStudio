import {test, expect} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';

test('実PDFをアップロードして日本語音声付き5〜10分のMP4を生成・再生・保存する', async ({page, request}) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const health = await request.get('/api/health');
  const readiness = await health.json();
  expect(readiness.codex_available).toBe(true);
  expect(readiness.voicevox_ready).toBe(true);
  await page.goto('/');
  await expect(page.getByRole('heading', {name: '講義を、見て理解する。'})).toBeVisible();
  await page.getByLabel('講義PDF', {exact: true}).setInputFiles(path.resolve('tests/fixtures/search_algorithms.pdf'));
  await expect(page.getByRole('button', {name: '動画を生成', exact: false})).toBeEnabled();
  let project: {id: string; title?: string};
  const resumeId = process.env.LECTURE_E2E_PROJECT_ID;
  if (resumeId) {
    expect(resumeId).toMatch(/^[0-9a-f]{32}$/);
    const stored = await (await request.get(`/api/projects/${resumeId}`, {maxRetries: 3})).json();
    project = stored;
    expect(stored.filename).toBe('search_algorithms.pdf');
    await page.locator('.history-open').filter({hasText: stored.title}).first().click();
    console.log('既に実ブラウザでアップロード済みの講義を継続検証:', resumeId);
  } else {
    const created = page.waitForResponse(response => response.url().endsWith('/api/projects') && response.request().method() === 'POST');
    await page.getByRole('button', {name: '動画を生成', exact: false}).click();
    project = await (await created).json();
  }
  expect(project.id).toMatch(/^[0-9a-f]{32}$/);
  console.log('実サービス生成 project:', project.id);
  // Inspect the real persisted job; no route mocking or fixed success responses.
  let lastStage = '';
  await expect.poll(async () => {
    const response = await request.get(`/api/projects/${project.id}`, {maxRetries: 3});
    const item = await response.json();
    if (item.stage !== lastStage) {console.log('工程:', item.stage); lastStage = item.stage;}
    if (item.status === 'failed') throw new Error(`生成失敗: ${item.stage}: ${item.error}`);
    return item.status;
  }, {timeout: 7100_000, intervals: [1500, 3000, 5000]}).toBe('completed');
  await expect(page.getByRole('link', {name: 'MP4を保存', exact: false})).toBeVisible({timeout: 30_000});
  const final = await (await request.get(`/api/projects/${project.id}`)).json();
  expect(final.seconds).toBeGreaterThanOrEqual(300);
  expect(final.seconds).toBeLessThanOrEqual(600);
  expect(final.chapters.length).toBeGreaterThanOrEqual(6);
  const video = page.getByLabel('生成した講義動画');
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(1);
  expect(await video.evaluate((element: HTMLVideoElement, seconds: number) => Math.abs(element.duration - seconds), final.seconds)).toBeLessThan(0.2);
  await video.evaluate((element: HTMLVideoElement) => {element.muted = true; return element.play();});
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(0.1);
  await page.locator('.chapter-play').nth(1).click();
  expect(await video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThanOrEqual(final.chapters[1].seconds - 0.2);
  await page.locator('.page-link').first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect.poll(() => page.getByRole('dialog').locator('img').evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
  await page.getByLabel('資料を閉じる').click();
  const downloading = page.waitForEvent('download');
  await page.getByRole('link', {name: 'MP4を保存', exact: false}).click();
  const download = await downloading;
  const target = path.resolve(`data/e2e-${project.id}.mp4`);
  await download.saveAs(target);
  expect(fs.statSync(target).size).toBeGreaterThan(100_000);
  const metadata = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', target], {encoding: 'utf8'}));
  expect(metadata.streams.find((s: {codec_type: string}) => s.codec_type === 'video').codec_name).toBe('h264');
  expect(metadata.streams.find((s: {codec_type: string}) => s.codec_type === 'audio').codec_name).toBe('aac');
  await page.screenshot({path: path.resolve('data/mvp-completed.png'), fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  await expect(page.getByRole('link', {name: 'MP4を保存', exact: false})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path: path.resolve('data/mvp-mobile.png'), fullPage: true});
  expect(errors).toEqual([]);
  fs.writeFileSync(path.resolve('data/e2e-result.json'), JSON.stringify({project_id: project.id, seconds: final.seconds,
    chapter_count: final.chapters.length, codecs: ['h264', 'aac'], browser_playback: true,
    downloaded_bytes: fs.statSync(target).size, page_reference: true, mobile: true, resumed: Boolean(resumeId), page_errors: errors}, null, 2));
});

test('不正なPDFを拒否し、実PDFの解析失敗をUIで表示する', async ({page, request}) => {
  await page.goto('/');
  await page.getByLabel('講義PDF', {exact: true}).setInputFiles({name: 'invalid.pdf', mimeType: 'application/pdf', buffer: Buffer.from('not PDF')});
  await page.getByRole('button', {name: '動画を生成', exact: false}).click();
  await expect(page.getByRole('alert')).toContainText('PDFではありません');
  const created = page.waitForResponse(response => response.url().endsWith('/api/projects') && response.request().method() === 'POST');
  await page.getByLabel('講義PDF', {exact: true}).setInputFiles({name: 'broken.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7\nnot valid objects')});
  await page.getByRole('button', {name: '動画を生成', exact: false}).click();
  const item = await (await created).json();
  await expect(page.getByRole('button', {name: '保存済みの工程から再試行'})).toBeVisible();
  await page.getByRole('button', {name: '保存済みの工程から再試行'}).click();
  await expect.poll(async () => (await (await request.get(`/api/projects/${item.id}`)).json()).jobs.length).toBe(2);
  await expect(page.getByRole('button', {name: '保存済みの工程から再試行'})).toBeVisible();
  await request.delete(`/api/projects/${item.id}`);
});
