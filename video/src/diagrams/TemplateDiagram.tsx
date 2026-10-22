import React from 'react';
import {useCurrentFrame} from 'remotion';
import type {Animation, Palette} from '../types';

const curves: Record<string, (n: number) => number> = {
  constant: () => 1, log: Math.log2, linear: n => n, n_log_n: n => n * Math.log2(n),
  quadratic: n => n * n, cubic: n => n ** 3,
};
const curveLabels: Record<string, string> = {constant: 'O(1)', log: 'O(log n)', linear: 'O(n)', n_log_n: 'O(n log n)', quadratic: 'O(n²)', cubic: 'O(n³)'};

/** The same validated state snapshots remain usable when Manim is unavailable. */
export const TemplateDiagram: React.FC<{animation: Animation; palette: Palette}> = ({animation, palette}) => {
  const frame = useCurrentFrame();
  const state = animation.states.reduce((current, value) => value.at_frame <= frame ? value : current, animation.states[0]);
  const active = new Set(state.highlight);
  const point = (id: string): [number, number] => {
    const [x, y] = animation.positions?.[id] ?? [0, 0];
    return [848 + x * 120, 240 - y * 120];
  };
  const colors = [palette.accent, '#f3ae64', '#9c9eff', '#ed8ca2'];
  const positions = Object.values(animation.positions ?? {});
  const distances = positions.flatMap((a, i) => positions.slice(i + 1).map(b => Math.hypot(a[0] - b[0], a[1] - b[1]) * 120));
  const radius = Math.min(39, ...distances.map(distance => distance * .38));
  return <svg width="1696" height="480" viewBox="0 0 1696 480" role="img" aria-label={state.label || animation.template}>
    <defs><marker id="template-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill={palette.muted}/></marker></defs>
    {animation.template === 'array' ? state.values.map((value, i) => {
      const x = 848 + (i - (state.values.length - 1) / 2) * 168;
      return <g key={i}><rect x={x - 63} y={147} width={126} height={126} rx={10} fill={palette.card} stroke={active.has(String(i)) ? palette.accent : palette.border} strokeWidth={5}/><text x={x} y={225} textAnchor="middle" fill={palette.fg} fontSize={String(value).length > 6 ? 23 : 36}>{value}</text><text x={x} y={317} textAnchor="middle" fill={palette.muted} fontSize={24}>{i}</text></g>;
    }) : null}
    {['tree', 'graph'].includes(animation.template) ? <>
      {animation.edges.map(edge => {
        const [x1, y1] = point(edge.source), [x2, y2] = point(edge.target);
        return <g key={edge.id}><line x1={x1} y1={y1} x2={x2} y2={y2} stroke={active.has(edge.id) ? palette.accent : palette.muted} strokeWidth={4} markerEnd="url(#template-arrow)"/><text x={(x1+x2)/2} y={(y1+y2)/2 - 16} textAnchor="middle" fill={palette.fg} fontSize={22}>{edge.label}</text></g>;
      })}
      {animation.nodes.map(node => {const [x, y] = point(node.id); const size = Math.min(28, radius * 1.1); return <g key={node.id}><circle cx={x} cy={y} r={radius} fill={palette.bg} stroke={active.has(node.id) ? palette.accent : palette.muted} strokeWidth={5}/><text x={x} y={y + size / 3} textAnchor="middle" fill={palette.fg} fontSize={size} textLength={node.label.length > 5 ? 180 : undefined} lengthAdjust="spacingAndGlyphs">{node.label}</text></g>;})}
    </> : null}
    {animation.template === 'formula' ? <text x={848} y={240} textAnchor="middle" fill={palette.fg} fontSize={state.formula.length > 40 ? 32 : 52} textLength={state.formula.length > 55 ? 1400 : undefined} lengthAdjust="spacingAndGlyphs">{state.formula}</text> : null}
    {animation.template === 'complexity' ? <>
      <path d="M 272 90 V 360 H 1290" fill="none" stroke={palette.muted} strokeWidth={3}/>
      <text x={720} y={392} fill={palette.muted} fontSize={22}>n: 入力サイズ (1〜4)</text><text x={272} y={60} fill={palette.muted} fontSize={22}>操作回数 (0〜64)</text>
      {animation.curves.map((curve, i) => {
        const points = Array.from({length: 80}, (_, j) => {const n = 1 + 3*j/79; return `${272+(n-1)/3*960},${360-curves[curve](n)/64*240}`;}).join(' ');
        return <g key={curve}><polyline points={points} fill="none" stroke={colors[i]} strokeWidth={active.has(curve) ? 6 : 3}/><text x={1370} y={120+i*60} fill={colors[i]} fontSize={27}>{curveLabels[curve]}</text></g>;
      })}
    </> : null}
    <text x={848} y={454} textAnchor="middle" fill={palette.fg} fontSize={29} textLength={state.label.length > 40 ? 1500 : undefined} lengthAdjust="spacingAndGlyphs">{state.label}</text>
  </svg>;
};
