import React from 'react';
import {useCurrentFrame} from 'remotion';
import type {Palette, Storyboard, StoryElement} from './types';
import {storyboardElements} from './storyboard.mjs';

const Label: React.FC<{element: StoryElement; color: string}> = ({element: e, color}) => {
  if (!e.text) return null;
  const lines = e.text.split('\n');
  const padding = e.kind === 'text' ? 0 : 12;
  const x = e.align === 'left' ? e.x + padding : e.align === 'right' ? e.x + e.width - padding : e.x + e.width / 2;
  const anchor = e.align === 'left' ? 'start' : e.align === 'right' ? 'end' : 'middle';
  const lineHeight = e.font_size * 1.25;
  return <text x={x} y={e.y + e.height / 2 - (lines.length - 1) * lineHeight / 2} textAnchor={anchor}
    dominantBaseline="central" fill={color} fontSize={e.font_size} fontWeight={650}>
    {lines.map((line, i) => <tspan key={i} x={x} dy={i ? lineHeight : 0}>{line}</tspan>)}
  </text>;
};

/** Content owns the canvas, including titles; subtitles keep their own region. */
export const StoryboardView: React.FC<{board: Storyboard; palette: Palette}> = ({board, palette}) => {
  const frame = useCurrentFrame();
  const colors = {...palette, none: 'none', warm: '#d17b37', cool: '#8586d9'};
  return <svg width="1696" height="668" viewBox="0 0 1696 668" role="img" aria-label={board.intent} style={{overflow: 'hidden'}}>
    {storyboardElements(board, frame).map(e => {
      const stroke = colors[e.tone], fill = colors[e.fill];
      if (e.kind === 'line' || e.kind === 'arrow') {
        const endX = e.x + e.width, endY = e.y + e.height;
        const angle = Math.atan2(e.height, e.width), size = 18;
        const tip = `${endX},${endY} ${endX - size * Math.cos(angle - .45)},${endY - size * Math.sin(angle - .45)} ${endX - size * Math.cos(angle + .45)},${endY - size * Math.sin(angle + .45)}`;
        return <g key={e.id} opacity={e.opacity}><line x1={e.x} y1={e.y} x2={endX} y2={endY} stroke={stroke} strokeWidth={4}/>
          {e.kind === 'arrow' ? <polygon points={tip} fill={stroke}/> : null}</g>;
      }
      return <g key={e.id} opacity={e.opacity}>
        {e.kind === 'rect' ? <rect x={e.x} y={e.y} width={e.width} height={e.height} rx={16} fill={fill} stroke={stroke} strokeWidth={3}/> : null}
        {e.kind === 'ellipse' ? <ellipse cx={e.x + e.width / 2} cy={e.y + e.height / 2} rx={e.width / 2} ry={e.height / 2} fill={fill} stroke={stroke} strokeWidth={3}/> : null}
        <Label element={e} color={stroke}/>
      </g>;
    })}
  </svg>;
};
