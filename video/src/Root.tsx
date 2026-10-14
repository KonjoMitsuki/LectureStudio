import {Composition} from 'remotion';
import {LectureVideo} from './Composition';
import type {LectureProps} from './types';

const preview: LectureProps = {
  title: 'Lecture Studio', style: 'motion', duration_in_frames: 300,
  scenes: [{id: 'scene_001', title: '講義を、見て理解する。', narration: '', concepts: ['資料', '理解', '復習'], source_pages: [1], supplemental: false,
    audio_src: '', audio_seconds: 9.5, start_frame: 0, duration_in_frames: 300,
    visual: {type: 'flowchart', nodes: [{id: 'pdf', label: '講義PDF'}, {id: 'script', label: '内容の整理'}, {id: 'video', label: '図解と音声'}],
      edges: [{id: 'a', source: 'pdf', target: 'script', label: ''}, {id: 'b', source: 'script', target: 'video', label: ''}],
      items: [], columns: [], rows: [], formula: '', steps: [{action: 'highlight_node', target: 'pdf'}, {action: 'highlight_node', target: 'script'}, {action: 'highlight_node', target: 'video'}]}}],
};

export const RemotionRoot = () => <Composition id="Lecture" component={LectureVideo} width={1920} height={1080} fps={30}
  durationInFrames={preview.duration_in_frames} defaultProps={preview}
  calculateMetadata={({props}) => ({durationInFrames: props.duration_in_frames})}/>;
