export type Visual = {
  type: 'flowchart' | 'state_diagram' | 'block_diagram' | 'network' | 'timeline' | 'comparison' | 'formula' | 'keywords';
  nodes: {id: string; label: string}[];
  edges: {id: string; source: string; target: string; label: string}[];
  items: string[]; columns: string[]; rows: string[][]; formula: string;
  steps: {action: 'reveal' | 'highlight_node' | 'highlight_edge' | 'highlight_item'; target: string; cue?: string; at_frame?: number}[];
};
export type Caption = {text: string; start_frame: number; end_frame: number};
export type StoryTone = 'fg' | 'muted' | 'accent' | 'warm' | 'cool';
export type StoryState = {
  x: number; y: number; width: number; height: number; text: string; font_size: number;
  tone: StoryTone; fill: 'none' | 'card' | 'accent' | 'warm' | 'cool'; opacity: number;
};
export type StoryElement = StoryState & {id: string; kind: 'text' | 'rect' | 'ellipse' | 'line' | 'arrow'; align: 'left' | 'center' | 'right'};
export type StoryChange = {target: string} & {[K in keyof StoryState]?: StoryState[K] | null};
export type StoryBeat = {cue: string; transition_seconds: number; changes: StoryChange[]; at_frame: number; duration_in_frames: number};
export type Storyboard = {intent: string; elements: StoryElement[]; beats: StoryBeat[]};
export type Animation = {
  template: 'array' | 'tree' | 'graph' | 'formula' | 'complexity';
  nodes: Visual['nodes']; edges: Visual['edges']; curves: string[];
  positions?: Record<string, [number, number]>;
  states: {values: number[]; highlight: string[]; label: string; formula: string; cue: string; at_frame: number}[];
};
export type Scene = {
  id: string; title: string; narration: string; concepts: string[]; source_pages: number[];
  kind?: 'lecture' | 'quiz' | 'quiz_answer'; thinking_seconds?: number; thinking_start_frame?: number;
  captions?: Caption[];
  renderer?: 'remotion' | 'manim'; animation?: Animation | null; manim_src?: string | null;
  storyboard?: Storyboard | null;
  supplemental: boolean; visual: Visual; audio_src: string; audio_seconds: number;
  duration_in_frames: number; start_frame: number;
};
export type LectureProps = {title: string; scenes: Scene[]; style: 'whiteboard' | 'motion' | 'slides'; duration_in_frames: number};
export type Palette = {bg: string; fg: string; muted: string; accent: string; card: string; border: string};
export const palettes: Record<LectureProps['style'], Palette> = {
  motion: {bg: '#101e32', fg: '#f3f7fc', muted: '#99afc9', accent: '#4fdbc4', card: '#1c304a', border: '#355271'},
  whiteboard: {bg: '#faf9f4', fg: '#203245', muted: '#6a7887', accent: '#008779', card: '#ffffff', border: '#bdced2'},
  slides: {bg: '#edf2f8', fg: '#172c46', muted: '#667c93', accent: '#2664db', card: '#ffffff', border: '#c4d2e3'},
};
