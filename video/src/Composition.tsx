import React from 'react';
import {AbsoluteFill, Html5Audio, Sequence, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {captionAt, thinkingRemaining} from './timeline.mjs';
import {Diagram} from './diagrams/Diagram';
import {palettes, type LectureProps, type Scene} from './types';

const SceneView: React.FC<{scene: Scene; style: LectureProps['style']; index: number; total: number}> = ({scene, style, index, total}) => {
  const frame = useCurrentFrame();
  const palette = palettes[style];
  const caption = captionAt(scene.captions, frame);
  const remaining = thinkingRemaining(scene, frame);
  const label = scene.kind === 'quiz' ? '理解チェック' : scene.kind === 'quiz_answer' ? '正答と解説' : 'LECTURE STUDIO';
  const opacity = interpolate(frame, [0, 12, scene.duration_in_frames - 10, scene.duration_in_frames - 1], [0, 1, 1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return <AbsoluteFill style={{backgroundColor: palette.bg, color: palette.fg, padding: '48px 112px', fontFamily: '"Droid Sans Fallback", "Noto Sans CJK JP", sans-serif'}}>
    <div style={{opacity, display: 'flex', flexDirection: 'column', height: '100%'}}>
      <div style={{display: 'flex', justifyContent: 'space-between', color: palette.muted, fontSize: 27, letterSpacing: 2}}><span style={{color: scene.kind === 'quiz' ? palette.accent : palette.muted}}>{label}</span><span>{String(index + 1).padStart(2, '0')} / {String(total).padStart(2, '0')}</span></div>
      <h1 style={{fontSize: scene.title.length > 22 ? 58 : 72, fontWeight: 750, margin: '24px 0 10px', lineHeight: 1.2}}>{scene.title}</h1>
      <div style={{width: 100, height: 6, background: palette.accent, marginTop: 16}}/>
      <div style={{flex: 1, minHeight: 0, display: 'flex', alignItems: 'center', padding: '16px 0'}}><Diagram visual={scene.visual} palette={palette} duration={scene.duration_in_frames} allowHighlight={scene.kind !== 'quiz'}/></div>
      <div style={{height: 140, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '12px 0'}}>
        {remaining > 0 ? <div style={{fontSize: 44, color: palette.accent, fontWeight: 700}}>考えてみましょう · あと{remaining}秒</div> : caption ? <div style={{maxWidth: 1440, padding: '16px 32px', borderRadius: 16, background: '#09111eee', color: '#ffffff', fontSize: 44, lineHeight: 1.35, textAlign: 'center', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere'}}>{caption.text.replace(/\s+/g, ' ')}</div> : null}
      </div>
      <div style={{display: 'flex', justifyContent: 'space-between', fontSize: 27, color: palette.muted, gap: 30}}><span>{scene.concepts.join(' · ')}</span><span>{scene.supplemental ? '補足説明 · ' : ''}{scene.source_pages.length ? `資料 p.${scene.source_pages.join(', ')}` : '資料外の補足'}</span></div>
    </div>
  </AbsoluteFill>;
};

export const LectureVideo: React.FC<LectureProps> = ({scenes, style}) => <AbsoluteFill>
  {scenes.map((scene, index) => <Sequence key={scene.id} name={scene.title} from={scene.start_frame} durationInFrames={scene.duration_in_frames}>
    <SceneView scene={scene} style={style} index={index} total={scenes.length}/>
    {scene.audio_src ? <Html5Audio src={staticFile(scene.audio_src)}/> : null}
  </Sequence>)}
</AbsoluteFill>;
