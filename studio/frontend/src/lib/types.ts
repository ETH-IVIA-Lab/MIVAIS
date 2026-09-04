export interface TaskRun {
  task_id: string;
  task_index: number;
  started_at: string;
  ended_at: string | null;
  answer: unknown;
  duration_ms: number | null;
  timed_out: boolean;
  skipped: boolean;
  score: number | null;
  correct: boolean | null;
  score_details: Record<string, unknown> | null;
  checked_steps: string[];
}

export interface Participant {
  id: string;
  session_id: string;
  study_id: string;
  anon_id: string;
  role: string | null;
  code_id: string | null;
  external_id: string | null;
  recruitment: Record<string, string>;
  status: "joined" | "consented" | "lobby" | "ready" | "in_session" | "finished" | "dropped";
  biometric_status: "not_asked" | "connected" | "skipped" | "unsupported";
  joined_at: string;
  consented_at: string | null;
  ready_at: string | null;
  finished_at: string | null;
  applied_task_order: string[];
  flow_pointer: number;
  task_runs: TaskRun[];
  user_agent: string | null;
}

export interface StudyRole {
  id: string;
  name?: string;
  description?: string;
  color?: string | null;
  selectable?: boolean;
  capacity?: number | null;
  agent_id?: string;
  wizard_panel?: boolean;
  [key: string]: unknown;
}

export interface Study {
  id: string;
  slug: string;
  name: string;
  version: number;
  mode: "singleplayer" | "multiplayer";
  participants_required: number | null;
  consent_text_md: string;
  consent_text_md_by_lang: Record<string, string>;
  va_systems: Record<string, Record<string, unknown>>;
  primary_va_system: string | null;
  roles: StudyRole[];
  advance_policy: string;
  recording: { audio?: string; video?: string; biometric?: boolean; external_sensor?: boolean; [key: string]: unknown };
  ui: Record<string, unknown>;
  blocks: Array<Record<string, unknown>>;
  parameters: Record<string, unknown>;
  completion_redirect_url: string | null;
  completion_code: string | null;
  archived: boolean;
}

export interface SessionDoc {
  id: string;
  study_id: string;
  mode: "singleplayer" | "multiplayer";
  status: "pending" | "lobby" | "spawning" | "running" | "completed" | "failed" | "abandoned" | "interrupted";
  created_at: string;
  current_task_index: number;
  applied_task_order: string[];
  tags: string[];
}

// ── participant flow response envelopes ────────────────────────────────

export interface NextResponse {
  next?: string;
  error?: string;
  external_redirect?: string;
}

export interface ConsentResponse extends NextResponse {
  participant?: Participant;
  study?: Study;
  consent_html?: string;
}

export interface BiometricResponse extends NextResponse {
  participant?: Participant;
  study?: Study;
}

export interface PreflightResponse {
  code: string;
  study: Study | null;
  audio_required: boolean;
  valid_code: boolean;
}

export interface RoleOption extends StudyRole {
  available: number | null;
  taken: number;
}

export interface RolePickerResponse extends NextResponse {
  participant?: Participant;
  study?: Study;
  roles?: RoleOption[];
}

export interface RoleStateResponse {
  error?: string;
  redirect?: string;
  roles?: RoleOption[];
}

export interface LobbyParticipant {
  anon_id: string;
  role: string | null;
  status: string;
  is_self: boolean;
}

export interface LobbyPageResponse extends NextResponse {
  participant?: Participant;
  study?: Study;
  session?: SessionDoc;
  participants?: Participant[];
  required?: number;
}

export interface LobbyStateResponse {
  error?: string;
  session_status?: string;
  required?: number;
  released?: boolean;
  participants?: LobbyParticipant[];
  ready_count?: number;
}

export interface ParticipantStateResponse {
  error?: string;
  session_status?: string;
  session_task_index?: number;
  participant_status?: string;
  seconds_until_auto_advance?: number | null;
}

export interface TaskStep {
  id: string;
  label: string;
  required?: boolean;
  mode?: "auto" | "manual" | "either";
  auto_check_on?: { meta?: Record<string, unknown>; event_type?: string };
  [key: string]: unknown;
}

export interface TaskOption {
  id: string;
  label: string;
}

export interface LikertItem {
  id: string;
  label: string;
  description?: string;
}

export interface Task {
  id: string;
  type:
    | "info_screen"
    | "single_choice"
    | "multi_choice"
    | "likert"
    | "slider"
    | "number_input"
    | "free_text"
    | "va_interaction"
    | string;
  with_va?: boolean;
  va_system?: string;
  variant?: string;
  optional?: boolean;
  task_steps?: TaskStep[];
  items?: LikertItem[];
  options?: TaskOption[];
  scale?: { min: number; max: number; step: number; min_label?: string; max_label?: string };
  timer_seconds?: number;
  continue_label?: string;
  video_url?: string | null;
  rows?: number;
  min_chars?: number;
  max_chars?: number;
  placeholder?: string;
  // slider / number_input
  min?: number;
  max?: number;
  step?: number;
  min_label?: string;
  max_label?: string;
  unit?: string;
  default_value?: number | null;
  show_value?: boolean;
  answer?: { type: "text" | "capture_state" | string; world_state_key?: string };
  prompt_html?: string;
  body_html?: string;
  [key: string]: unknown;
}

export interface TaskPageResponse extends NextResponse {
  interrupted?: boolean;
  participant?: Participant;
  study?: Study;
  session?: SessionDoc;
  ui?: Record<string, unknown>;
  task?: Task;
  task_index?: number;
  total_tasks?: number;
  block_id?: string;
  iframe_url?: string | null;
  waiting_for_cohort?: boolean;
  is_wizard?: boolean;
}

export interface TaskStepsResponse {
  task_id: string | null;
  checked: string[];
}

export interface FinishResponse extends NextResponse {
  completion_code?: string | null;
  participant?: Participant;
  study?: Study;
}

export interface WizardPeer {
  id: string;
  anon_id: string;
  role: string | null;
  status: string;
  task_id: string | null;
  task_index: number;
  is_self: boolean;
}
