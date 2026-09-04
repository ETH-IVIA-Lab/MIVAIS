/**
 * Wire types for the `mivais` backend protocol shared by MIVAIS-based visual
 * analytics apps. See the Python `mivais.gateway.Gateway`
 * class for the authoritative server-side implementation of this contract.
 */

export interface AuditEntry {
  id: string;
  timestamp: string;
  actor: string;
  key: string;
  value_repr?: string;
  accepted?: boolean;
  event_type?: "write" | "denied" | "bus_message" | "cursor_move" | "user_input" | string;
}

export interface ConnectedUser {
  session_id: string;
  role: string;
}

export interface CursorInfo {
  row_name?: string | null;
  x?: number | null;
  y?: number | null;
  dragging?: string | null;
  drag_over?: string | null;
}

/** Keyed by agent/user id, e.g. `"user:<sessionId>"`. */
export type CursorMap = Record<string, CursorInfo>;

export interface OnlineAgent {
  id: string;
  role: string;
  description?: string;
}

export interface Permissions {
  role: string;
  can_write: string[];
  bus_publish_topics: string[];
}

export interface BusMessageEnvelope<TPayload = Record<string, unknown>> {
  id: string;
  timestamp: string;
  sender: string;
  topic: string;
  payload: TPayload;
}

export interface ChatPayload {
  from: string;
  from_display?: string;
  from_role?: string;
  to: string;
  text: string;
  timestamp: string | number;
  [key: string]: unknown;
}

interface ServerMessageCommon<TWorldState> {
  cursors?: CursorMap;
  connected_users?: ConnectedUser[];
  online_agents?: OnlineAgent[];
  world_state?: Partial<TWorldState>;
  audit_log?: AuditEntry[];
}

export interface InitialStateMessage<TWorldState> extends ServerMessageCommon<TWorldState> {
  type: "initial_state";
  world_state: Partial<TWorldState>;
  audit_log: AuditEntry[];
  cursors: CursorMap;
  connected_users: ConnectedUser[];
  my_permissions: Permissions;
  chat_history: Array<{ payload?: ChatPayload } & Partial<ChatPayload>>;
  online_agents: OnlineAgent[];
}

export interface StateUpdateMessage<TWorldState> extends ServerMessageCommon<TWorldState> {
  type: "state_update";
  world_state: Partial<TWorldState>;
  audit_log: AuditEntry[];
}

export interface CursorUpdateMessage {
  type: "cursor_update";
  cursors: CursorMap;
  connected_users: ConnectedUser[];
}

export interface BusMessageFrame {
  type: "bus_message";
  message: BusMessageEnvelope;
}

export type ServerMessage<TWorldState> =
  | InitialStateMessage<TWorldState>
  | StateUpdateMessage<TWorldState>
  | CursorUpdateMessage
  | BusMessageFrame;

export type ConnectionStatus = "connecting" | "connected" | "reconnecting";

/** Every outbound action carries a string `action` discriminator plus payload. */
export interface BaseAction {
  action: string;
  [key: string]: unknown;
}
