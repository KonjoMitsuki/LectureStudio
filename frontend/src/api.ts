export type Options = {duration: 'test' | 'short' | 'medium' | 'long'; level: 'beginner' | 'standard' | 'detailed'; style: 'whiteboard' | 'motion' | 'slides'; speaker: number; speed: number};
export type Chapter = {id: string; title: string; seconds: number; source_pages: number[]; supplemental: boolean};
export type Project = {id: string; title: string; filename: string; created_at: string; status: 'uploaded' | 'queued' | 'running' | 'completed' | 'failed'; stage: string; progress: number | null; error: string | null; settings: Options; warnings: string[]; chapters: Chapter[]; page_count: number | null; seconds: number | null};
export type Speaker = {id: number; name: string; credit: string};
export type Health = {codex_available: boolean; ffmpeg_available: boolean; voicevox_ready: boolean};
export type GenerationEvent = {id: number; created_at: string; stage: string; level: 'info' | 'success' | 'warning' | 'error'; message: string; details: string[]};
export type Diagnostics = {
  jobs: {id: string; created_at: string; status: string; stage: string; error: string | null}[];
  selected_job_id: string | null;
  activity: {
    running: boolean; task: string; completed_stages: string[]; elapsed_seconds: number; stage_elapsed_seconds: number;
    heartbeat_at: string; heartbeat_age_seconds: number; activity_age_seconds: number; output_age_seconds: number | null;
    process_elapsed_seconds: number | null;
    ai?: {phase: string; completed: number; total: number; event_count: number; last_event?: string;
      calls: number; usage: {input_tokens?: number; cached_input_tokens?: number; output_tokens?: number}} | null;
    process: {alive: boolean; status: string; timeout_seconds: number} | null;
  } | null;
  events: GenerationEvent[]; has_more: boolean;
  artifact_summaries: {name: string; description: string; bytes: number}[];
};

export async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${url}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `処理に失敗しました (${response.status})`);
  }
  return response.status === 204 ? undefined as T : response.json();
}
export const time = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
