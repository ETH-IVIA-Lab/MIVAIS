import type { BaseAction } from "mivais-va-client";

export type FieldType = "quantitative" | "nominal" | "temporal" | "ordinal";

export interface DataField {
  field: string;
  type: FieldType;
  is_count?: boolean;
}

export interface EncodingEntry {
  channel?: string;
  field: string;
  type: string;
  aggregate?: string;
  bin?: boolean;
  timeUnit?: string;
}

export interface ViewSpec {
  mark: string;
  encoding?: Record<string, { field: string; type: string; aggregate?: string; bin?: boolean; timeUnit?: string }>;
  encodings?: EncodingEntry[];
  _title?: string;
  _score?: number;
}

export interface Bookmark {
  view: ViewSpec;
  note?: string;
  by?: string;
}

export interface OnlineAgentRef {
  id?: string;
  agent_id?: string;
  role?: string;
}

export interface FilterSpec {
  field: string;
  type: "quantitative" | "nominal";
  min?: number;
  max?: number;
  values?: string[];
  /** Exclude null/NaN rows for this field (vega-lite `valid` predicate). */
  valid?: boolean;
}

export interface VoyagerWorldState {
  dataset: Record<string, unknown>[];
  /** Name of the loaded dataset (data/<name>.json), chosen via ?dataset=. */
  dataset_name: string;
  data_fields: DataField[];
  current_spec: { mark: string; encodings: EncodingEntry[] };
  focus_view: ViewSpec | null;
  wildcard_results: ViewSpec[];
  related_summaries: ViewSpec[];
  field_suggestions: ViewSpec[];
  alt_encodings: ViewSpec[];
  bookmarks: Bookmark[];
  /** Shared chart filters — applied to every rendered view. */
  filters: FilterSpec[];
}

export type VoyagerAction =
  | ({ action: "set_filters"; filters: FilterSpec[] } & BaseAction)
  | ({ action: "load_dataset"; name: string; dataset: Record<string, unknown>[] } & BaseAction)
  | ({ action: "update_spec"; spec: { mark: string; encodings: EncodingEntry[] } } & BaseAction)
  | ({ action: "specify_view"; view: ViewSpec } & BaseAction)
  | ({ action: "select_insight_action"; suggestion: { label?: string; spec?: unknown; filter_nulls?: { field: string } } } & BaseAction)
  | ({ action: "add_bookmark"; view: ViewSpec; note: string } & BaseAction)
  | ({ action: "update_bookmark_note"; index: number; note: string } & BaseAction)
  | ({ action: "remove_bookmark"; index: number } & BaseAction);

export const CHANNELS = ["x", "y", "color", "size", "shape", "row", "column"] as const;
export type Channel = (typeof CHANNELS)[number];

export const TYPE_ABBR: Record<FieldType, string> = { quantitative: "Q", nominal: "N", temporal: "T", ordinal: "O" };
export const TYPE_COLOR: Record<string, string> = { Q: "var(--blue)", N: "var(--green)", T: "var(--amber)", O: "var(--purple)" };

export interface ShelfEntry {
  field: string;
  type: string;
  aggregate: string;
  bin: boolean;
  timeUnit: string;
}
