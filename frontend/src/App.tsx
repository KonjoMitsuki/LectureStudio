import {useCallback, useEffect, useRef, useState} from 'react';
import {api, time, type Health, type Options, type Project, type Speaker} from './api';

const stages = [{id: 'pdf', label: 'PDFを解析'}, {id: 'ai', label: '講義と台本を構成'}, {id: 'audio', label: '日本語音声を合成'}, {id: 'render', label: '図解動画を生成'}];
const labels: Record<string, string> = {uploaded: '準備完了', queued: '順番待ち', running: '生成中', completed: '完成', failed: '要確認'};
const initial: Options = {duration: 'short', level: 'beginner', style: 'motion', speaker: 3, speed: 1};

function BookIcon({size = 22}: {size?: number}) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 5c-3-2-7-2-10-1v15c3-1 7-1 10 1m0-15c3-2 7-2 10-1v15c-3-1-7-1-10 1V5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/></svg>;
}

export function App() {
  const [file, setFile] = useState<File | null>(null);
  const [options, setOptions] = useState(initial);
  const [projects, setProjects] = useState<Project[]>([]);
  const [active, setActive] = useState<Project | null>(null);
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [notice, setNotice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const [currentChapter, setCurrentChapter] = useState(0);
  const video = useRef<HTMLVideoElement>(null);
  const uploadInput = useRef<HTMLInputElement>(null);
  const refresh = useCallback(async () => setProjects(await api<Project[]>('/projects')), []);

  useEffect(() => {
    const controller = new AbortController();
    const init = {signal: controller.signal};
    void Promise.allSettled([api<Project[]>('/projects', init), api<Health>('/health', init), api<Speaker[]>('/speakers', init)]).then(([list, status, voices]) => {
      if (controller.signal.aborted) return;
      if (list.status === 'fulfilled') setProjects(list.value);
      else setNotice('アプリの接続を確認してください。バックエンドの起動が必要です。');
      if (status.status === 'fulfilled') setHealth(status.value);
      if (voices.status === 'fulfilled') setSpeakers(voices.value);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!active || !['queued', 'running'].includes(active.status)) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const item = await api<Project>(`/projects/${active.id}`, {signal: controller.signal});
        if (controller.signal.aborted) return;
        setActive(item);
        if (['completed', 'failed'].includes(item.status)) {await refresh(); return;}
      } catch (error) {
        if (!controller.signal.aborted) setNotice(error instanceof Error ? error.message : '進捗を取得できません');
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 1500);
    };
    timer = setTimeout(poll, 500);
    return () => {controller.abort(); clearTimeout(timer);};
  }, [active?.id, active?.status, refresh]);

  const chooseFile = (value: File | undefined) => {
    setNotice('');
    if (!value) return;
    if (!value.name.toLowerCase().endsWith('.pdf')) {setNotice('講義PDFを選択してください。'); return;}
    if (value.size > 30 * 1024 * 1024) {setNotice('PDFは30MB以下にしてください。'); return;}
    setFile(value);
  };

  async function generate() {
    if (!file || submitting) return;
    setSubmitting(true); setNotice(''); setSelectedPage(null); setCurrentChapter(0);
    try {
      const form = new FormData(); form.append('file', file); form.append('options', JSON.stringify(options));
      const item = await api<Project>('/projects', {method: 'POST', body: form});
      setActive(item);
      await api(`/projects/${item.id}/generate`, {method: 'POST'});
      setActive(await api<Project>(`/projects/${item.id}`));
      await refresh();
    } catch (error) {setNotice(error instanceof Error ? error.message : '生成を開始できません');}
    finally {setSubmitting(false);}
  }

  async function retry(item: Project) {
    setSubmitting(true); setNotice(''); setSelectedPage(null);
    try {
      await api(`/projects/${item.id}/generate`, {method: 'POST'});
      setActive(await api<Project>(`/projects/${item.id}`)); await refresh();
    } catch (error) {setNotice(error instanceof Error ? error.message : '再試行できません');}
    finally {setSubmitting(false);}
  }

  async function remove(item: Project) {
    try {
      await api(`/projects/${item.id}`, {method: 'DELETE'});
      if (active?.id === item.id) setActive(null);
      await refresh();
    } catch (error) {setNotice(error instanceof Error ? error.message : '削除できません');}
  }

  const stageIndex = stages.findIndex(stage => stage.id === active?.stage);
  const busy = active?.status === 'queued' || active?.status === 'running';
  const credit = speakers.find(speaker => speaker.id === active?.settings.speaker)?.credit ?? 'VOICEVOX';

  return <>
    <header className="topbar"><a className="brand" href="/" aria-label="Lecture Studio ホーム"><span className="brand-icon"><BookIcon/></span>Lecture <strong>Studio</strong></a><div className="local-label"><span className="status-dot"/> YOUR LOCAL WORKSPACE</div></header>
    <main>
      <div className="intro"><div><div className="eyebrow">FROM NOTES TO UNDERSTANDING</div><h1>講義を、<span>見て理解する。</span></h1><p>いつものPDFから、図解と日本語音声の学習動画へ。</p></div><div className="output-spec"><span>1080p</span><small>MP4 / 30fps / 日本語</small></div></div>
      <div className="workspace">
        <section className="setup panel" aria-labelledby="setup-title">
          <div className="section-heading"><span className="step-number">01</span><h2 id="setup-title">動画をつくる</h2></div>
          <input ref={uploadInput} id="pdf-upload" className="sr-only" type="file" accept=".pdf,application/pdf" aria-label="講義PDF" onChange={event => chooseFile(event.target.files?.[0])}/>
          <button className={`dropzone ${dragging ? 'dragging' : ''} ${file ? 'has-file' : ''}`} type="button" onClick={() => uploadInput.current?.click()}
            onDragOver={event => {event.preventDefault(); setDragging(true);}} onDragLeave={() => setDragging(false)} onDrop={event => {event.preventDefault(); setDragging(false); chooseFile(event.dataTransfer.files[0]);}}>
            <span className="pdf-icon"><BookIcon size={32}/></span><strong>{file ? file.name : '講義PDFを選択'}</strong><span>{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB · クリックして変更` : 'ここにドラッグ、またはクリック'}</span><small>PDF · 最大30MB / 100ページ</small>
          </button>
          <div className="settings-grid">
            <label>動画の長さ<select value={options.duration} onChange={e => setOptions({...options, duration: e.target.value as Options['duration']})}><option value="short">5〜10分</option><option value="medium">15〜20分</option><option value="long">30分程度</option><option value="test">約1分（動作確認）</option></select></label>
            <label>解説レベル<select value={options.level} onChange={e => setOptions({...options, level: e.target.value as Options['level']})}><option value="beginner">初学者向け</option><option value="standard">標準</option><option value="detailed">詳しく</option></select></label>
            <label className="wide">映像スタイル<select value={options.style} onChange={e => setOptions({...options, style: e.target.value as Options['style']})}><option value="motion">モーショングラフィックス</option><option value="whiteboard">ホワイトボード</option><option value="slides">図解スライド</option></select></label>
            <label className="wide">ナレーション<select value={options.speaker} onChange={e => setOptions({...options, speaker: Number(e.target.value)})}>{speakers.length ? speakers.map(s => <option value={s.id} key={s.id}>{s.name}</option>) : <option value="3">ずんだもん（ノーマル） / ENGINE起動後に選択可能</option>}</select></label>
            <label className="wide speed-label"><span>読み上げ速度 <strong>{options.speed.toFixed(1)}×</strong></span><input type="range" min="0.7" max="1.4" step="0.1" value={options.speed} onChange={e => setOptions({...options, speed: Number(e.target.value)})}/></label>
          </div>
          <button className="primary generate-button" onClick={generate} disabled={!file || submitting || busy}>{submitting ? '準備しています…' : busy ? '動画を生成中' : '動画を生成'}<span aria-hidden="true">↗</span></button>
          <p className="privacy-note">PDFの抽出テキストとページ番号をCodexに送信します。音声と動画はこのPCで生成します。</p>
          <div className="service-status"><span className={health?.codex_available ? 'ok' : ''}>● Codex CLI</span><span className={health?.voicevox_ready ? 'ok' : ''}>● VOICEVOX</span><button type="button" onClick={() => {void Promise.all([api<Health>('/health'), api<Speaker[]>('/speakers')]).then(([h, s]) => {setHealth(h); setSpeakers(s); setNotice('');}).catch(error => setNotice(error.message));}}>接続を確認</button></div>
        </section>
        <section className="viewer panel" aria-labelledby="viewer-title">
          <div className="section-heading"><span className="step-number">02</span><h2 id="viewer-title">学びを再生する</h2>{active ? <span className={`badge ${active.status}`}>{labels[active.status]}</span> : null}</div>
          {notice ? <div className="notice" role="alert">{notice}</div> : null}
          {!active ? <div className="empty-state"><div className="illustration"><span className="diagram-box">講義PDF</span><span className="diagram-connector">→</span><span className="diagram-box accent-box">図解と音声</span></div><h3>理解が、動きはじめる。</h3><p>PDFを選んで「動画を生成」を押すと、<br/>ここにあなただけの講義動画が届きます。</p><div className="empty-tags"><span>内容を整理</span><span>図解で説明</span><span>音声で復習</span></div></div> : <>
            <div className="project-heading"><h3>{active.title}</h3><p>{active.filename}{active.page_count ? ` · ${active.page_count}ページ` : ''}{active.seconds ? ` · ${time(active.seconds)}` : ''}</p></div>
            {active.status === 'completed' ? <>
              <video key={active.id} ref={video} className="video-player" controls preload="metadata" aria-label="生成した講義動画" src={`/api/projects/${active.id}/video`} onTimeUpdate={() => {
                const index = active.chapters.findLastIndex(chapter => chapter.seconds <= (video.current?.currentTime ?? 0));
                setCurrentChapter(index < 0 ? 0 : index);
              }}/>
              <div className="video-actions"><a className="primary download" href={`/api/projects/${active.id}/video?download=true`} download>MP4を保存 <span aria-hidden="true">↓</span></a><a href={`/api/projects/${active.id}/source`} target="_blank" rel="noreferrer">元のPDFを確認 ↗</a><span className="voice-credit">{credit}</span></div>
              <h4 className="chapters-title">CHAPTERS <span>{active.chapters.length}シーン</span></h4>
              <div className="chapters">{active.chapters.map((chapter, i) => <div className={`chapter ${i === currentChapter ? 'selected' : ''}`} key={chapter.id}><button className="chapter-play" onClick={() => {if (video.current) {video.current.currentTime = chapter.seconds; void video.current.play().catch(() => {});} setCurrentChapter(i);}}><span className="chapter-index">{String(i + 1).padStart(2, '0')}</span><span>{chapter.title}<small>{chapter.supplemental ? '補足説明' : '資料からの解説'}</small></span><time>{time(chapter.seconds)}</time></button>{chapter.source_pages.length ? <button className="page-link" onClick={() => setSelectedPage(chapter.source_pages[0])}>p.{chapter.source_pages.join(', ')}</button> : null}</div>)}</div>
              <p className="accuracy-note">AIの解説には誤りが含まれる場合があります。参照ページと照合して学習してください。</p>
            </> : <div className="generation-state">
              {active.status === 'failed' ? <div className="error-box" role="alert"><strong>生成を続けられませんでした</strong><p>{active.error}</p><button className="primary" onClick={() => retry(active)} disabled={submitting}>保存済みの工程から再試行</button><a href={`/api/projects/${active.id}/diagnostics`} target="_blank" rel="noreferrer">診断情報を開く ↗</a></div> : <div className="progress-caption"><span className={busy ? 'working-indicator' : ''}/><strong>{active.status === 'queued' ? 'ほかの講義の完了を待っています' : active.status === 'uploaded' ? '生成の準備ができました' : '学びの映像を組み立てています'}</strong><p>この画面を閉じても、アプリを起動している間は生成が続きます。</p>{active.status === 'uploaded' ? <button className="primary" onClick={() => retry(active)}>生成を開始</button> : null}</div>}
              <ol className="stage-list">{stages.map((stage, i) => <li key={stage.id} className={i === stageIndex ? 'current' : i < stageIndex ? 'done' : ''}><span className="stage-icon">{i < stageIndex ? '✓' : String(i + 1).padStart(2, '0')}</span><span>{stage.label}</span>{i === stageIndex && active.status === 'running' ? <small>{active.progress !== null ? `${Math.floor(active.progress * 100)}%` : '処理中'}</small> : null}</li>)}</ol>
              {active.progress !== null && active.status === 'running' ? <progress aria-label="現在の工程の進捗" max={1} value={active.progress}/> : null}
            </div>}
            {active.warnings.length ? <details className="warnings"><summary>資料と生成結果の確認事項（{active.warnings.length}件）</summary><ul>{active.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul></details> : null}
          </>}
        </section>
      </div>
      <section className="history" aria-labelledby="history-title"><div className="history-heading"><h2 id="history-title">あなたの学習ライブラリ</h2><span>{projects.length}件</span></div>{projects.length ? <div className="history-grid">{projects.map(item => <article className={`history-card ${active?.id === item.id ? 'active' : ''}`} key={item.id}><button className="history-open" onClick={() => {setActive(item); setSelectedPage(null); setNotice(''); setCurrentChapter(0);}}><div className="history-card-top"><BookIcon/><span className={`badge ${item.status}`}>{labels[item.status]}</span></div><h3>{item.title}</h3><p>{new Date(item.created_at).toLocaleDateString('ja-JP')}{item.seconds ? ` · ${time(item.seconds)}` : ''}</p></button><div className="history-card-actions"><button onClick={() => retry(item)} disabled={['queued', 'running'].includes(item.status) || submitting}>再生成</button><button className="delete" aria-label={`${item.title}を削除`} onClick={() => remove(item)} disabled={['queued', 'running'].includes(item.status)}>削除</button></div></article>)}</div> : <p className="history-empty">完成した動画も、生成途中の講義もここに保存されます。</p>}</section>
      <footer><span>Lecture Studio · 自分のペースで、理解を深める。</span><span>音声：VOICEVOX · 映像：Remotion</span></footer>
    </main>
    {selectedPage !== null && active ? <div className="modal-backdrop" onClick={() => setSelectedPage(null)}><section className="page-modal" role="dialog" aria-modal="true" aria-label={`元の資料 ${selectedPage}ページ`} onClick={event => event.stopPropagation()}><div><h3>資料 p.{selectedPage}</h3><button autoFocus onClick={() => setSelectedPage(null)} aria-label="資料を閉じる">✕</button></div><img alt={`元の講義PDF ${selectedPage}ページ`} src={`/api/projects/${active.id}/pages/${selectedPage}`}/></section></div> : null}
  </>;
}
