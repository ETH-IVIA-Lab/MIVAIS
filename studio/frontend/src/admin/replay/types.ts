export interface ReplayEventMeta {
  actor?: string;
  action?: string;
  data?: unknown;
  key?: string;
  event_type?: string;
  value_repr?: string;
  accepted?: boolean;
  sender?: string;
  topic?: string;
  text?: string | null;
  payload_preview?: string;
  [key: string]: unknown;
}

export interface ReplayCursor {
  x?: number;
  y?: number;
  row_name?: string | null;
}

export interface ReplayEvent {
  t_ms: number;
  source: string;
  type: string;
  task_id: string | null;
  participant_id: string | null;
  va?: string;
  snapshot_index?: number;
  cursors?: Record<string, ReplayCursor>;
  meta?: ReplayEventMeta;
  taxonomy_category?: string;
  taxonomy_label?: string;
}


export interface ReplayVideoSegment {
  t_ms: number;
  video_t_ms: number;
  dur_ms: number;
}

export interface ReplayVideo {
  run_id: string;
  participant_id: string | null;
  label: string;
  src: string;
  start_t_ms: number;
  t_ms_end: number;
  duration_ms?: number;
  segments?: ReplayVideoSegment[];
  transcribe: boolean;
}

export interface AudioStripChunk {
  participant_id: string;
  t_ms_start: number;
  t_ms_end: number;
  envelope: number[];
}

export interface HeartRateSample {
  participant_id: string;
  t_ms: number;
  bpm: number;
}

export interface SensorSample {
  participant_id: string;
  t_ms: number;
  value: number;
}

export interface ReplayParticipantInfo {
  anon_id: string;
  role: string | null;
}

export interface ReplayPayload {
  session_id: string;
  t_max: number;
  timeline: ReplayEvent[];
  snapshots: Record<string, unknown>[];
  n_events: number;
  audio_strip: AudioStripChunk[];
  video: ReplayVideo | null;
  videos: ReplayVideo[];
  participants: Record<string, ReplayParticipantInfo>;
  task_va?: Record<string, string | null>;
  heart_rate: HeartRateSample[];
  sensor_channels: Record<string, SensorSample[]>;
  categories?: ReplayCategoryDef[];
}

export interface ReplayCategoryDef {
  key: string;
  label?: string;
  color?: string;
}

export interface AbsentSpan {
  t0: number;
  t1: number;
  reason: string;
}

export interface ReplayMarker {
  marker_id: string;
  author: string;
  t_ms: number;
  kind: string;
  label: string;
  quote?: string;
  wall_clock: string;
}

export interface ReplayNote {
  author: string;
  t_ms: number | null;
  wall_clock: string;
  text: string;
}

export type BuiltinEventCategory = "cursor" | "ranking" | "chat" | "agent" | "task" | "presence" | "state" | "other";
export type EventCategory = BuiltinEventCategory | (string & {});

export interface Classification {
  cat: EventCategory;
  label: string;
  actor?: string;
  filterKeys: string[];
  color: string;
}

export type ClassifiedEvent = ReplayEvent & { _c: Classification };

export interface Lane {
  key: string;
  label: string;
  color: string;
}
