import {useEffect, useState} from 'react';
import {api, type Diagnostics, type GenerationEvent, type Project} from './api';

const stageNames = [{id: 'pdf', label: 'PDF'}, {id: 'ai', label: '構成・台本'}, {id: 'audio', label: '音声'}, {id: 'render', label: '動画'}];
const eventLabels = {info: '進行', success: '成功', warning: '確認', error: '失敗'};
const jobLabels: Record<string, string> = {queued: '順番待ち', running: '生成中', completed: '完成', failed: '失敗'};
const elapsed = (seconds: number) => {
  const value = Math.max(0, Math.floor(seconds));
  return value >= 60 ? `${Math.floor(value / 60)}分${value % 60}秒` : `${value}秒`;
};
const clock = (value: string) => new Date(value).toLocaleTimeString('ja-JP', {hour12: false, timeZone: 'Asia/Tokyo'});

function EventList({events}: {events: GenerationEvent[]}) {
  return <ol className="generation-events">{events.slice().reverse().map(event => <li key={event.id} className={`event-${event.level}`}>
    <div className="event-meta"><time dateTime={event.created_at}>{clock(event.created_at)}</time><span>{eventLabels[event.level]}</span></div>
    <div><p>{event.message}</p>{event.details.length ? <details><summary>内容を見る</summary><ul>{event.details.map((line, i) => <li key={i}>{line}</li>)}</ul></details> : null}</div>
  </li>)}</ol>;
}

export function DiagnosticsPanel({project}: {project: Project}) {
  const [data, setData] = useState<Diagnostics | null>(null);
  const [error, setError] = useState('');
  const [jobId, setJobId] = useState('');
  const {id, status, stage} = project;
  useEffect(() => {
    if (status === 'queued' || status === 'running') setJobId('');
  }, [status]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await api<Diagnostics>(`/projects/${id}/diagnostics${jobId ? `?job_id=${jobId}` : ''}`, {signal: controller.signal});
        if (controller.signal.aborted) return;
        setData(result); setError('');
      } catch {
        if (!controller.signal.aborted) setError('処理の記録を取得できません。アプリとの接続を確認してください。');
      }
      if (!controller.signal.aborted && (status === 'running' || status === 'queued')) timer = setTimeout(poll, 3000);
    };
    void poll();
    return () => {controller.abort(); clearTimeout(timer);};
  }, [id, status, jobId]);

  const activity = data?.activity;
  const selected = data?.jobs.find(job => job.id === data.selected_job_id);
  const selectedStatus = selected?.status ?? status;
  const selectedStage = selected?.stage ?? stage;
  const live = activity?.running && selectedStatus === 'running';
  const fresh = !error && !!activity && activity.heartbeat_age_seconds <= 45;
  const scriptReady = data?.artifact_summaries.some(artifact => artifact.name === 'lecture.json');

  return <section className="diagnostics-panel" aria-labelledby="diagnostics-title">
    <div className="diagnostics-heading"><h4 id="diagnostics-title">処理の記録</h4><a href={`/api/projects/${id}/logs?download=true`} download>全記録を保存 ↓</a></div>
    {error ? <p className="diagnostics-error" role="status">{error}</p> : null}
    {data && data.jobs.length > 1 ? <label className="attempt-select">生成の履歴<select aria-label="表示する生成の履歴" value={jobId} onChange={event => {setJobId(event.target.value); setData(null);}}>
      <option value="">最新の生成</option>{data.jobs.slice(1).map((job, i) => <option key={job.id} value={job.id}>{data.jobs.length - i - 1}回目 · {new Date(job.created_at).toLocaleString('ja-JP', {timeZone: 'Asia/Tokyo'})} · {jobLabels[job.status]}</option>)}
    </select></label> : null}
    {activity ? <div className={`activity-summary ${live && !fresh ? 'activity-stale' : ''}`}>
      <strong>{live ? fresh ? 'バックグラウンド処理の稼働を確認できています' : '稼働確認の更新が止まっています。アプリの状態を確認してください' : jobLabels[selectedStatus] ?? '処理の記録'}</strong>
      <p>{activity.task}</p>
      <div className="activity-times"><span>開始から {elapsed(activity.elapsed_seconds)}</span><span>この工程 {elapsed(activity.stage_elapsed_seconds)}</span></div>
      {live ? <>
        <p>最終稼働確認：{clock(activity.heartbeat_at)}（{elapsed(activity.heartbeat_age_seconds)}前・約15秒ごとに確認）</p>
        <p>最後の進捗更新：{elapsed(activity.activity_age_seconds)}前</p>
        {activity.process?.status === 'running' ? <p>外部の生成処理：{activity.process.alive ? '前回確認時に動作中' : '終了を確認中'} / 待機上限 {elapsed(activity.process.timeout_seconds)}{activity.process_elapsed_seconds !== null ? `（経過 ${elapsed(activity.process_elapsed_seconds)}）` : ''}<br/>{activity.output_age_seconds === null ? 'まだ応答は届いていません。' : `外部処理からの最後の応答：${elapsed(activity.output_age_seconds)}前。`} 応答待ちの間は進捗率が変わらない場合があります。</p> : null}
      </> : null}
    </div> : !error ? <p className="diagnostics-note">{selectedStatus === 'queued' ? '順番を待っています。処理が始まると稼働状況を表示します。' : data?.events.length ? 'この試行の処理の記録を表示しています。' : data ? 'この生成の稼働記録はありません。追加したログは次の生成から記録されます。' : '処理の記録を読み込んでいます…'}</p> : null}
    <ul className="diagnostic-stages">{stageNames.map((item, index) => {
      const done = activity?.completed_stages.includes(item.id) || selectedStatus === 'completed'
        || (['failed', 'running'].includes(selectedStatus) && index < stageNames.findIndex(value => value.id === selectedStage));
      const failed = selectedStatus === 'failed' && item.id === selectedStage;
      const running = selectedStatus === 'running' && item.id === selectedStage;
      const text = done ? '成功' : failed ? '失敗' : running ? '実行中' : '待機';
      return <li key={item.id} className={done ? 'done' : failed ? 'failed' : running ? 'running' : ''}><span>{item.label}</span><strong>{text}</strong></li>;
    })}</ul>
    {data?.events.length ? <>
      <p className="diagnostics-note">新しい記録から表示しています。生成内容の抜粋は「内容を見る」で確認できます。</p>
      <EventList events={data.events.slice(-6)}/>
      {data.events.length > 6 ? <details className="earlier-events"><summary>それ以前の記録を見る{data.has_more ? '（画面は最新120件まで・全件は保存できます）' : `（${data.events.length - 6}件）`}</summary><EventList events={data.events.slice(0, -6)}/></details> : null}
    </> : null}
    {data?.artifact_summaries.length ? <details className="artifact-list"><summary>保存済みの生成物を見る（現在のファイル）</summary>
      {scriptReady ? <a className="transcript-link" href={`/api/projects/${id}/transcript`} target="_blank" rel="noreferrer">台本の全文を読む ↗</a> : null}
      <ul>{data.artifact_summaries.map(artifact => <li key={artifact.name}><span>{artifact.description}<small>{artifact.name} · {artifact.bytes >= 1024 * 1024 ? `${(artifact.bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(artifact.bytes / 1024)} KB`}</small></span></li>)}</ul>
    </details> : null}
  </section>;
}
