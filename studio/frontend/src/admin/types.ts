import type { Study } from "../lib/types";

export interface AdminStudyRow {
  study: Study;
  n_sessions: number;
  n_completed: number;
}

export interface OverviewStats {
  n_studies: number;
  n_sessions: number;
  n_sessions_completed: number;
  n_participants: number;
  n_participants_finished: number;
  n_events: number;
  completion_rate: number;
}

export interface DashboardExtras {
  active_now: number;
  sessions_today: number;
  sessions_7d: number;
  n_abandoned: number;
  by_mode: Record<string, number>;
  n_markers: number;
  n_notes: number;
  n_annotations: number;
  avg_duration_s: number;
  avg_duration_human: string;
  n_with_duration: number;
}

export interface TimeseriesPoint {
  date: string;
  label: string;
  total: number;
  completed: number;
}

export interface StatusBreakdownEntry {
  status: string;
  count: number;
}

export interface DashboardResponse {
  per_study: AdminStudyRow[];
  per_study_archived: AdminStudyRow[];
  overview: OverviewStats;
  extras: DashboardExtras;
  timeseries: TimeseriesPoint[];
  status_breakdown: StatusBreakdownEntry[];
}

export interface AvailableStudy {
  dir_name: string;
  slug: string | null;
  name: string | null;
  version: number | null;
  mode: string | null;
  digest: string | null;
  status: "not_registered" | "in_sync" | "out_of_sync" | "error";
  registered_id: string | null;
  error: string | null;
}

export interface AdminCode {
  id: string;
  code: string;
  study_id: string;
  role: string | null;
  active: boolean;
  uses: number;
  max_uses: number | null;
  expires_at: string | null;
  multiplayer_session_id: string | null;
  created_at: string;
}

export interface AdminSession {
  id: string;
  study_id: string;
  mode: string;
  status: string;
  created_at: string;
  va_started_at: string | null;
  ended_at: string | null;
  current_task_index: number;
  tags: string[];
  tags_by_author: Record<string, string[]>;
  notes: Array<{ author: string; t_ms: number; wall_clock: string; text: string }>;
  markers: Array<{ author: string; t_ms: number; kind: string; label: string; wall_clock: string }>;
  vas: Record<string, { pid: number | null; port: number | null; iframe_url: string | null; variant: string | null }>;
}

export interface StudyStats {
  n_sessions: number;
  n_sessions_completed: number;
  n_sessions_in_progress: number;
  n_sessions_failed: number;
  n_participants: number;
  n_participants_finished: number;
  completion_rate: number;
  mean_duration_s: number;
  median_duration_s: number;
  n_events: number;
  n_events_mivais: number;
  n_events_studio: number;
  last_session_at: string | null;
}

export interface PerTaskSummaryRow {
  task_id: string;
  type: string;
  block_id: string;
  n_runs: number;
  n_timed_out: number;
  n_skipped: number;
  mean_duration_ms: number;
  median_duration_ms: number;
  has_ground_truth: boolean;
  n_with_score: number;
  correct_rate: number;
  mean_score: number;
  answer_distribution: Array<{ label: string; count: number; percent: number }>;
}

export interface StudyDetailResponse {
  study: Study;
  codes: AdminCode[];
  sessions: AdminSession[];
  stats: StudyStats;
  tasks: PerTaskSummaryRow[];
  share_base: string;
}

export interface SessionsRow {
  session: AdminSession;
  study: Study | null;
  n_participants: number;
  n_finished: number;
}

export interface SavedView {
  id: string;
  owner_username: string;
  name: string;
  query: string;
  surface: string;
  created_at: string;
}

export interface SessionsIndexResponse {
  rows: SessionsRow[];
  all_studies: Study[];
  study_filter: string;
  status_filter: string;
  tag_filter: string;
  saved_views: SavedView[];
  all_tags: string[];
  current_query: string;
}

export interface AdminUserRow {
  id: string;
  username: string;
  created_at: string;
  last_login: string | null;
}

export interface AuditEntry {
  id: string;
  actor_username: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  meta: Record<string, unknown>;
  ts: string;
}

// ── analytics ────────────────────────────────────────────────

export interface FunnelStage {
  name: string;
  count: number;
  pct: number;
  _alt?: boolean;
}

export interface FunnelResponse {
  study: Study;
  stages: FunnelStage[];
}

export interface CompareRow {
  study: Study;
  task_id: string | null;
  task_found?: boolean;
  n_runs: number;
  mean_duration_ms: number | null;
  median_duration_ms?: number | null;
  correct_rate?: number | null;
  n_timed_out?: number;
  n_skipped?: number;
  distribution?: Array<{ label: string; count: number; percent: number }>;
  n_sessions?: number;
  n_sessions_completed?: number;
  n_participants?: number;
  n_participants_finished?: number;
  completion_rate?: number;
  mean_duration_s?: number;
  n_events?: number;
}

export interface CompareInference {
  metric: string;
  label_a: string;
  label_b: string;
  welch: { t: number; df: number; p_two_sided: number | null };
  cohens_d: number | null;
  mann_whitney: { u: number; p_two_sided: number | null };
  n_a: number;
  n_b: number;
}

export interface ComparePayload {
  studies: Study[];
  rows: CompareRow[];
  task_id: string | null;
  inference: CompareInference | null;
}

export interface CompareResponse {
  all_studies: Study[];
  payload: ComparePayload | null;
  selected_slugs: string[];
  task_id: string;
  shared_task_ids: string[];
}

export interface DurationBucket {
  lo_ms: number;
  hi_ms: number;
  count: number;
}

export interface LikertHeatmap {
  items: Array<{ id: string; label: string }>;
  scale_min: number;
  scale_max: number;
  cells: number[][];
  row_max: number[];
}

export interface TaskRunRow {
  started_at: string | null;
  duration_ms: number | null;
  answer: unknown;
  score: number | null;
  correct: boolean | null;
  timed_out: boolean;
  skipped: boolean;
}

export interface TaskDrilldownPayload {
  task: Record<string, unknown> | null;
  n_runs: number;
  n_timed_out: number;
  n_skipped: number;
  n_correct: number;
  n_with_score: number;
  correct_rate: number;
  mean_score: number;
  mean_duration_ms: number;
  median_duration_ms: number;
  distribution: Array<{ label: string; count: number; percent: number }>;
  duration_buckets: DurationBucket[];
  likert_heatmap: LikertHeatmap | null;
  answers: unknown[];
  runs: TaskRunRow[];
}

export interface TaskDrilldownResponse {
  study: Study;
  payload: TaskDrilldownPayload;
  task_id: string;
}

export interface ParticipantJourneyTaskRun {
  task_index: number;
  task_id: string;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  answer: unknown;
  score: number | null;
  correct: boolean | null;
  timed_out: boolean;
  skipped: boolean;
  checked_steps: string[];
  n_events: number;
  n_mivais: number;
  n_studio: number;
}

export interface ParticipantJourneyPayload {
  participant: {
    id: string;
    anon_id: string;
    role: string | null;
    status: string;
    external_id: string | null;
    joined_at: string;
    finished_at: string | null;
    applied_task_order: string[];
    shuffle_seed: number | null;
  };
  session: AdminSession | null;
  study: Study | null;
  task_runs: ParticipantJourneyTaskRun[];
  events: unknown[];
  transcripts: Array<{ t_ms_start: number; language: string | null; text: string }>;
  final_state: Record<string, unknown> | null;
  n_events: number;
}

export interface ParticipantJourneyResponse {
  payload: ParticipantJourneyPayload;
}

export interface IrrResult {
  kappa: number | null;
  agreement: number;
  expected: number;
  interpretation: string;
  paired_n: number;
  tag: string;
  a: string;
  b: string;
}

export interface IrrResponse {
  all_studies: Study[];
  selected_study: string;
  raters: string[];
  all_tags: string[];
  selected_a: string;
  selected_b: string;
  selected_tag: string;
  result: IrrResult | null;
}

export interface LiveSessionResponse {
  session: AdminSession;
  study: Study;
  spectator_urls: Array<{ va_system_id: string; url: string }>;
}

export interface LivePollParticipant {
  id: string;
  anon_id: string;
  role: string | null;
  status: string;
  task_index: number;
  current_task_id: string | null;
  checked_steps: string[];
  vu: number;
}

export interface LivePollEvent {
  t_ms: number;
  source: string;
  type: string;
  task_id: string | null;
  va_system_id: string | null;
  meta: Record<string, unknown>;
}

export interface LivePollResponse {
  session: { id: string; status: string; mode: string; current_task_index: number };
  participants: LivePollParticipant[];
  events: LivePollEvent[];
  audio_chunks: number;
  transcripts: number;
  recent_transcripts: Array<{
    t_ms_start: number;
    text: string;
    language: string | null;
    participant_anon: string | null;
    role: string | null;
  }>;
}

// ── webhooks ─────────────────────────────────────────────────────────────

export interface WebhookOut {
  id: string;
  study_id: string;
  url: string;
  events: string[];
  kind: string;
  active: boolean;
  description: string;
  created_at: string;
  last_delivery_at: string | null;
  last_delivery_status: number | null;
  delivery_count: number;
  failure_count: number;
}

export interface WebhookStudyRef {
  id: string;
  slug: string;
  name: string;
}

export interface WebhooksIndexResponse {
  rows: { hook: WebhookOut; study: WebhookStudyRef | null }[];
  all_studies: WebhookStudyRef[];
}

export const WEBHOOK_EVENTS = [
  "session_started",
  "session_completed",
  "session_failed",
  "participant_finished",
  "code_minted",
] as const;
