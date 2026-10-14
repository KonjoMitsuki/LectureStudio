import React, {useMemo} from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import katex from 'katex';
import type {Palette, Visual} from '../types';
import {revealFrame, stepFrame} from '../timeline.mjs';
import 'katex/dist/katex.min.css';

const enter = (frame: number, start: number) => interpolate(frame, [start, start + 20], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
const chunks = (text: string, size: number) => Array.from(text).reduce<string[]>((lines, char, i) => {
  const index = Math.floor(i / size); lines[index] = (lines[index] ?? '') + char; return lines;
}, []);

const SvgLabel: React.FC<{text: string; x: number; y: number; fill: string; size?: number; wrap?: number}> = ({text, x, y, fill, size = 40, wrap = 9}) => {
  const lines = chunks(text, wrap);
  return <text x={x} y={y} fill={fill} fontSize={size} textAnchor="middle" fontWeight={650}>
    {lines.map((line, i) => <tspan key={i} x={x} dy={i === 0 ? -(lines.length - 1) * size * 0.55 : size * 1.1}>{line}</tspan>)}
  </text>;
};

const Graph: React.FC<{visual: Visual; palette: Palette; frame: number; active: string | undefined; spacing: number; duration: number}> = ({visual, palette, frame, active, spacing, duration}) => {
  const {nodes, edges} = visual;
  const circular = ['network', 'state_diagram'].includes(visual.type);
  const positions = new Map(nodes.map((n, i) => {
    const angle = (i / nodes.length) * Math.PI * 2 - Math.PI / 2;
    const cols = nodes.length <= 3 ? nodes.length : 3;
    const rows = Math.ceil(nodes.length / cols);
    return [n.id, circular && nodes.length > 2
      ? {x: 832 + Math.cos(angle) * 560, y: 310 + Math.sin(angle) * 190}
      : {x: (i % cols + 0.5) * (1664 / cols), y: rows === 1 ? 310 : 160 + Math.floor(i / cols) * 300}];
  }));
  return <svg viewBox="0 0 1664 620" width="100%" height="100%">
    <defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10" fill={palette.accent}/></marker></defs>
    {edges.map((edge, i) => {
      const from = positions.get(edge.source)!; const to = positions.get(edge.target)!;
      const dx = to.x - from.x, dy = to.y - from.y;
      const factor = Math.min(0.42, Math.min(220 / (Math.abs(dx) || 1), 85 / (Math.abs(dy) || 1)));
      const x1 = from.x + dx * factor, y1 = from.y + dy * factor;
      const x2 = to.x - dx * factor, y2 = to.y - dy * factor;
      const amount = enter(frame, revealFrame(visual, duration, edge.id, 10 + i * spacing));
      return <g key={edge.id} opacity={amount}>
        <line x1={x1} y1={y1} x2={x1 + (x2 - x1) * amount} y2={y1 + (y2 - y1) * amount} stroke={active === edge.id ? palette.fg : palette.accent} strokeWidth={active === edge.id ? 7 : 4} markerEnd="url(#arrow)"/>
        {edge.label ? <SvgLabel text={edge.label} x={(from.x + to.x) / 2 + (Math.abs(dy) > Math.abs(dx) ? 110 : 0)} y={(from.y + to.y) / 2 - (Math.abs(dy) <= Math.abs(dx) ? 110 : 0)} fill={palette.muted} size={26} wrap={12}/> : null}
        {from.x === to.x && from.y === to.y ? <circle cx={from.x + 180} cy={from.y - 65} r={55} fill="none" stroke={palette.accent} strokeWidth={4}/> : null}
      </g>;
    })}
    {nodes.map((node, i) => {
      const p = positions.get(node.id)!; const amount = enter(frame, revealFrame(visual, duration, node.id, i * spacing));
      const selected = active === node.id;
      return <g key={node.id} opacity={amount} transform={`translate(${p.x},${p.y + 24 * (1 - amount)})`}>
        <rect x={-220} y={-84} width={440} height={168} rx={visual.type === 'state_diagram' ? 80 : 24} fill={selected ? palette.accent : palette.card} stroke={selected ? palette.accent : palette.border} strokeWidth={selected ? 5 : 2}/>
        <SvgLabel text={node.label} x={0} y={12} fill={selected ? palette.bg : palette.fg}/>
      </g>;
    })}
  </svg>;
};

const Items: React.FC<{visual: Visual; palette: Palette; frame: number; active: string | undefined; spacing: number; duration: number}> = ({visual, palette, frame, active, spacing, duration}) => {
  const timeline = visual.type === 'timeline';
  return <div style={{display: 'grid', gridTemplateColumns: timeline ? '1fr' : '1fr 1fr', gap: 20, width: '100%', alignContent: 'center'}}>
    {visual.items.map((item, i) => {
      const amount = enter(frame, revealFrame(visual, duration, String(i), i * spacing)), selected = active === String(i);
      return <div key={i} style={{opacity: amount, transform: `translateY(${(1 - amount) * 24}px)`, display: 'flex', alignItems: 'center', gap: 24, padding: '20px 30px', borderRadius: 20, background: selected ? palette.accent : palette.card, color: selected ? palette.bg : palette.fg, border: `2px solid ${palette.border}`, fontSize: timeline ? 42 : 46, lineHeight: 1.35}}>
        <span style={{color: selected ? palette.bg : palette.accent, fontSize: 30, fontWeight: 800, minWidth: 50}}>{String(i + 1).padStart(2, '0')}</span><span>{item}</span>
      </div>;
    })}
  </div>;
};

const Comparison: React.FC<{visual: Visual; palette: Palette; frame: number; spacing: number; duration: number; active: string | undefined}> = ({visual, palette, frame, spacing, duration, active}) => <table style={{width: '100%', borderCollapse: 'separate', borderSpacing: '6px', fontSize: 38, lineHeight: 1.4, tableLayout: 'fixed'}}>
  <thead><tr>{visual.columns.map((column, i) => <th key={i} style={{padding: 22, background: palette.accent, color: palette.bg, borderRadius: 10}}>{column}</th>)}</tr></thead>
  <tbody>{visual.rows.map((row, i) => <tr key={i} style={{opacity: enter(frame, revealFrame(visual, duration, String(i), i * spacing))}}>{row.map((cell, j) => <td key={j} style={{padding: '20px 24px', background: active === String(i) ? palette.accent : palette.card, color: active === String(i) ? palette.bg : palette.fg, borderRadius: 10, overflowWrap: 'anywhere', fontSize: cell.length > 25 ? 30 : 38}}>{cell}</td>)}</tr>)}</tbody>
</table>;

const Formula: React.FC<{formula: string; palette: Palette; frame: number}> = ({formula, palette, frame}) => {
  const markup = useMemo(() => katex.renderToString(formula, {throwOnError: false, trust: false, strict: 'error', maxExpand: 100, maxSize: 15, output: 'html'}), [formula]);
  return <div style={{opacity: enter(frame, 0), padding: 70, borderRadius: 32, background: palette.card, color: palette.fg, fontSize: 74, width: '100%', overflow: 'hidden', textAlign: 'center'}} dangerouslySetInnerHTML={{__html: markup}}/>;
};

export const Diagram: React.FC<{visual: Visual; palette: Palette; duration: number; allowHighlight?: boolean}> = ({visual, palette, duration, allowHighlight = true}) => {
  const frame = useCurrentFrame();
  const count = Math.max(visual.nodes.length, visual.items.length, visual.rows.length, 1);
  const spacing = Math.max(20, Math.min(60, Math.floor(duration * 0.35 / count)));
  let active: string | undefined;
  visual.steps.forEach((step, index) => {
    if (allowHighlight && frame >= stepFrame(visual, duration, index)) active = step.target;
  });
  if (visual.type === 'formula') return <Formula formula={visual.formula} palette={palette} frame={frame}/>;
  if (visual.type === 'comparison') return <Comparison visual={visual} palette={palette} frame={frame} spacing={spacing} duration={duration} active={active}/>;
  if (['timeline', 'keywords'].includes(visual.type)) return <Items visual={visual} palette={palette} frame={frame} active={active} spacing={spacing} duration={duration}/>;
  return <Graph visual={visual} palette={palette} frame={frame} active={active} spacing={spacing} duration={duration}/>;
};
