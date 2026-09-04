import type { BaseAction } from "mivais-va-client";

export interface DatasetRow {
  name?: string;
  Name?: string;
  [key: string]: string | number | undefined;
}

export interface RankedItem {
  name?: string;
  Name?: string;
  score?: number;
  rank?: number;
  [key: string]: unknown;
}

export interface SvmStatus {
  status?: string;
  message?: string;
  n_items?: number;
  active_nudges?: Record<string, number>;
}

export interface PodiumWorldState {
  dataset: DatasetRow[];
  numeric_cols: string[];
  session_nudges: Record<string, -1 | 1>;
  user_preference_ranking: { ranking?: number[] };
  ranked_items: RankedItem[];
  display_order: string[];
  weights: Record<string, number>;
  svm_status: SvmStatus;
}

export type PodiumAction =
  | ({ action: "set_nudges"; nudges: Record<string, -1 | 1> } & BaseAction)
  | ({ action: "compute_weights"; ranking: number[] } & BaseAction)
  | ({ action: "drop_order"; display_order: string[] } & BaseAction)
  | ({ action: "rank_all" } & BaseAction)
  | ({ action: "drag_update"; dragging: string | null; drag_over: string | null } & BaseAction);

export function getRowName(row: { name?: string; Name?: string } | undefined | null): string {
  if (!row) return "?";
  if (row.name) return row.name;
  if (row.Name) return row.Name;
  const first = Object.values(row)[0];
  return first !== undefined ? String(first) : "?";
}
