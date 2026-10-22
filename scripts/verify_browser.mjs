// Read-only browser acceptance against an already generated lecture.
import fs from 'node:fs';
import path from 'node:path';
import {chromium, expect} from '@playwright/test';

const output = path.resolve(process.argv[2] || 'data/acceptance-20261021');
const baseURL = process.argv[3] || 'http://127.0.0.1:8001';
const {project_id: id} = JSON.parse(fs.readFileSync(path.join(output, 'acceptance_project.json'), 'utf8'));
const browser = await chromium.launch({chromiumSandbox: true});
try {
  const context = await browser.newContext({baseURL, acceptDownloads: true, viewport: {width: 1440, height: 1100}});
  const page = await context.newPage();
  let pageErrors = 0;
  page.on('pageerror', () => pageErrors++);
  const project = await (await context.request.get(`/api/projects/${id}`)).json();
  if (project.status !== 'completed') throw new Error('Lecture is not completed');
  const lecture = await (await context.request.get(`/api/projects/${id}/lecture`)).json();
  await page.goto('/');
  await page.locator('.history-open').filter({hasText: project.title}).first().click();
  const downloadLink = page.getByRole('link', {name: 'MP4を保存', exact: false});
  await expect(downloadLink).toBeVisible();
  const video = page.getByLabel('生成した講義動画');
  await expect.poll(() => video.evaluate(element => element.readyState)).toBeGreaterThanOrEqual(1);
  const difference = await video.evaluate((element, seconds) => Math.abs(element.duration - seconds), project.seconds);
  if (difference > .2) throw new Error('Browser duration differs from timeline');
  await video.evaluate(element => {element.muted = true; return element.play();});
  await expect.poll(() => video.evaluate(element => element.currentTime)).toBeGreaterThan(.1);
  await video.evaluate(element => element.pause());
  const manim = lecture.scenes.findIndex(scene => scene.renderer === 'manim');
  const target = manim >= 0 ? manim : Math.min(1, project.chapters.length - 1);
  await page.locator('.chapter-play').nth(target).click();
  await expect.poll(() => video.evaluate(element => element.currentTime)).toBeGreaterThanOrEqual(project.chapters[target].seconds - .2);
  await video.evaluate(element => element.play());
  await video.evaluate(element => element.pause());
  await page.locator('.page-link').first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect.poll(() => page.getByRole('dialog').locator('img').evaluate(element => element.naturalWidth)).toBeGreaterThan(0);
  await page.getByLabel('資料を閉じる').click();
  const download = page.waitForEvent('download');
  await downloadLink.click();
  const targetFile = path.join(output, 'browser-download.mp4');
  await (await download).saveAs(targetFile);
  await page.screenshot({path: path.join(output, 'browser-desktop.png'), fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  await expect(downloadLink).toBeVisible();
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
  if (!fits || pageErrors) throw new Error('Browser layout or runtime verification failed');
  await page.screenshot({path: path.join(output, 'browser-mobile.png'), fullPage: true});
  const result = {status: 'PASS', playback: true, chapter_seek: true, manim_scene_seek: manim >= 0,
    page_reference: true, download_bytes: fs.statSync(targetFile).size, mobile: true, page_errors: pageErrors,
    duration_difference_seconds: difference};
  fs.writeFileSync(path.join(output, 'browser_report.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} finally {
  await browser.close();
}
