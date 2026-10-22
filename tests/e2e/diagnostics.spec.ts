import {test, expect} from '@playwright/test';

test('処理の記録で稼働確認・使用量・分割進捗・以前の失敗を読める', async ({page}) => {
  const id = 'a'.repeat(32), latest = 'b'.repeat(32), previous = 'c'.repeat(32);
  const now = new Date().toISOString();
  const project = {id, title: '探索の講義', filename: 'lecture.pdf', created_at: now, status: 'running', stage: 'ai',
    progress: null, error: null, settings: {duration: 'long', level: 'beginner', style: 'motion', speaker: 3, speed: 1},
    warnings: [], chapters: [], page_count: 4, seconds: null};
  const jobs = [{id: latest, created_at: now, status: 'running', stage: 'ai', error: null},
    {id: previous, created_at: now, status: 'failed', stage: 'ai', error: '待機上限に達しました'}];
  const activity = {running: true, task: 'AIの台本作成の応答を待っています', completed_stages: ['pdf'], elapsed_seconds: 300,
    stage_elapsed_seconds: 290, heartbeat_at: now, heartbeat_age_seconds: 2, activity_age_seconds: 120,
    output_age_seconds: 90, process_elapsed_seconds: 280, process: {alive: true, status: 'running', timeout_seconds: 900},
    ai: {phase: 'chapters', completed: 2, total: 8, event_count: 12, calls: 3, usage: {input_tokens: 3200, output_tokens: 1400, cached_input_tokens: 500}}};
  const events = [{id: 1, created_at: now, stage: 'pdf', level: 'success', message: 'PDFを読み取れました', details: ['4ページ']},
    {id: 2, created_at: now, stage: 'ai', level: 'success', message: '解説項目の一覧ができました：8項目', details: ['保存先：ai/content_plan.json']},
    {id: 3, created_at: now, stage: 'ai', level: 'info', message: 'AIに台本の作成を依頼します', details: []}];
  let disconnected = false;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url());
    if (path.pathname.endsWith('/diagnostics')) {
      if (disconnected) {await route.abort(); return;}
      const old = path.searchParams.get('job_id') === previous;
      await route.fulfill({json: {jobs, selected_job_id: old ? previous : latest, activity: old ? null : activity,
        events: old ? [{id: 4, created_at: now, stage: 'ai', level: 'error', message: 'AIが待機上限の15分に達しました', details: []}] : events,
        has_more: false, artifact_summaries: [{name: 'lecture.json', description: '完成した台本と図解の構成', bytes: 12345}]}});
    } else if (path.pathname === '/api/projects') await route.fulfill({json: [project]});
    else if (path.pathname === `/api/projects/${id}`) await route.fulfill({json: project});
    else if (path.pathname === '/api/health') await route.fulfill({json: {codex_available: true, voicevox_ready: true, ffmpeg_available: true}});
    else if (path.pathname === '/api/speakers') await route.fulfill({json: []});
    else await route.fulfill({body: '生成の記録', contentType: 'text/plain'});
  });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.locator('.history-open').filter({hasText: '探索の講義'}).click();
  await expect(page.getByRole('heading', {name: '処理の記録'})).toBeVisible();
  await expect(page.getByText('バックグラウンド処理の稼働を確認できています')).toBeVisible();
  await expect(page.getByText('最後の進捗更新：2分0秒前')).toBeVisible();
  await expect(page.getByText('外部の生成処理：', {exact: false})).toContainText('待機上限 15分0秒');
  await page.locator('.generation-events li').filter({hasText: '解説項目の一覧ができました'}).getByText('内容を見る').click();
  await expect(page.getByText('保存先：ai/content_plan.json')).toBeVisible();
  await expect(page.getByText('章・トピックの台本：2/8 完了 · 受信イベント 12件')).toBeVisible();
  await expect(page.getByText('報告済みトークン：', {exact: false})).toContainText('入力 3,200 / 出力 1,400');
  await page.getByText('保存済みの生成物を見る', {exact: false}).click();
  await expect(page.getByRole('link', {name: '台本の全文を読む', exact: false})).toHaveAttribute('href', `/api/projects/${id}/transcript`);
  await expect(page.getByRole('link', {name: '全記録を保存', exact: false})).toHaveAttribute('href', `/api/projects/${id}/logs?download=true`);
  await page.getByLabel('表示する生成の履歴').selectOption(previous);
  await expect(page.getByText('AIが待機上限の15分に達しました')).toBeVisible();
  await expect(page.getByText('バックグラウンド処理の稼働を確認できています')).toHaveCount(0);
  await page.getByLabel('表示する生成の履歴').selectOption('');
  await expect(page.getByText('バックグラウンド処理の稼働を確認できています')).toBeVisible();
  activity.heartbeat_age_seconds = 60;
  await expect(page.getByText('稼働確認の更新が止まっています。アプリの状態を確認してください')).toBeVisible();
  await page.setViewportSize({width: 390, height: 844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path: 'test-results/diagnostics-mobile.png', fullPage: true});
  await page.setViewportSize({width: 1280, height: 1000});
  await page.screenshot({path: 'test-results/diagnostics-desktop.png', fullPage: true});
  disconnected = true;
  await expect(page.getByText('処理の記録を取得できません。アプリとの接続を確認してください。')).toBeVisible();
  expect(errors).toEqual([]);
});
