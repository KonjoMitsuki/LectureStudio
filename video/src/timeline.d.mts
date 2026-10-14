import type {Visual, Caption, Scene} from './types';
export function stepFrame(visual: Visual, duration: number, index: number): number;
export function revealFrame(visual: Visual, duration: number, target: string, fallback: number): number;
export function captionAt(captions: Caption[] | undefined, frame: number): Caption | undefined;
export function thinkingRemaining(scene: Scene, frame: number): number;
