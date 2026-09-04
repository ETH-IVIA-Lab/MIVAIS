import type { BaseAction } from "mivais-va-client";

// ── Data model ───────────────────────────────────────────────

export interface Mc3Message {
  id: string;
  type: "mbdata" | "ccdata" | string;
  timestamp: string;
  epoch: number;
  author?: string;
  message?: string;
  lat?: number | null;
  lon?: number | null;
  location?: string;
  sentiment?: "negative" | "positive" | "neutral" | string;
  entities?: string[];
  hex_id?: string | null;
}

export interface Hex {
  id: string;
  center: [number, number]; // [lon, lat]
  polygon: [number, number][]; // [lon, lat] pairs
}

export interface StaticData {
  dataset: Mc3Message[];
  hexgrid: Hex[];
  streets: GeoJSON.FeatureCollection;
  entities: unknown[];
  knowledge: Record<string, unknown>;
}

export interface TimeRange {
  start: number | null;
  end: number | null;
}

export interface NoteComment {
  type?: string; // factual_error | conflict | omission | note
  comment?: string;
  correction?: string;
  keywords?: string[];
}

export interface Note {
  id: string;
  by?: string;
  title?: string;
  label?: string;
  view?: string;
  hex_id?: string | null;
  evidence?: string[];
  comments?: NoteComment[];
  timestamp?: number;
}

export interface Suggestion {
  id: string;
  category?: string;
  subcategory?: string;
  pattern?: string;
  suggestion_text?: string;
  status?: "pending" | "acting" | "completed" | "rejected" | "dismissed" | string;
  popover?: { title?: string; view?: string; element?: string } | null;
}

export interface TraceStep {
  thought?: string;
  action?: string;
  action_args?: Record<string, unknown>;
  observation?: unknown;
}

// ── WorldState shape ─────────────────────────────────────────────────────────

export interface ProactiveWorldState {
  selected_hex: string | null;
  time_range: TimeRange | null;
  selected_entity: string | null;
  keyword_filter: string[];
  focused_view: string;
  notes: Note[];
  staged_evidence: string[];
  highlighted_message_ids: string[];
  pending_suggestions: Suggestion[];
  agent_trace: TraceStep[];
  agent_status: { state?: string };
  think_time_threshold_s: number;
  onboarding_enabled: boolean;
  exploration_enabled: boolean;
  verification_enabled: boolean;
  interaction_log: unknown[];
}

// ── Actions ──────────────────────────

export type ProactiveAction =
  | { action: "set_focus_view"; view: string }
  | { action: "select_hexagon"; hex_id: string }
  | { action: "set_time_range"; start: number | null; end: number | null }
  | { action: "select_message"; message_id: string }
  | { action: "clear_staged_evidence" }
  | { action: "hover_message"; message_id: string }
  | { action: "select_entity"; entity: string }
  | { action: "set_keyword_filter"; keywords: string[] }
  | {
      action: "add_note";
      title: string;
      label: string;
      view: string;
      evidence: string[];
      hex_id?: string;
    }
  | { action: "delete_note"; id: string }
  | { action: "highlight_messages"; message_ids: string[] }
  | { action: "accept_suggestion"; id: string }
  | { action: "reject_suggestion"; id: string }
  | { action: "set_threshold"; seconds: number }
  | { action: "set_toggle"; name: string; value: boolean }
  | (BaseAction & Record<string, unknown>);
