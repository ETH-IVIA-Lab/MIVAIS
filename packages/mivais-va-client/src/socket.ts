import type {
  BaseAction,
  BusMessageFrame,
  ConnectionStatus,
  CursorUpdateMessage,
  InitialStateMessage,
  ServerMessage,
  StateUpdateMessage,
} from "./types.js";

export interface MivaisSocketOptions {
  /** WebSocket session id — becomes the `/ws/{sessionId}` path segment. */
  sessionId: string;
  /** Isolated world to join (`?room=`). Defaults to `"default"`. */
  room?: string;
  /** Permission role to connect as (`?role=`). Defaults to `"analyst"`. */
  role?: string;
  /**
   * Host to connect to, e.g. `"localhost:8000"`. Defaults to `location.host`
   * (protocol-aware: `wss:` on `https:` pages, `ws:` otherwise).
   */
  host?: string;
  /** Fixed reconnect delay in ms. Defaults to 3000, matching the legacy apps. */
  reconnectDelayMs?: number;
  /**
   * Extra query params appended to the WS URL, e.g. `{dataset: "movies"}`.
   * App-specific — the server decides what (if anything) to do with them;
   * `room` and `role` must use their dedicated options, not this.
   */
  query?: Record<string, string>;
}

type Unsubscribe = () => void;

/**
 * Framework-agnostic client for the `mivais` Gateway WebSocket protocol.
 * Handles connection, protocol-aware URL construction, flat-delay
 * auto-reconnect, and typed message dispatch. No React dependency — see
 * `./react/createMivaisContext.ts` for the React binding.
 */
export class MivaisSocket<TWorldState = Record<string, unknown>> {
  private ws: WebSocket | null = null;
  private opts: Required<MivaisSocketOptions>;
  private closedByUser = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  private openHandlers = new Set<() => void>();
  private closeHandlers = new Set<() => void>();
  private initialStateHandlers = new Set<(msg: InitialStateMessage<TWorldState>) => void>();
  private stateUpdateHandlers = new Set<(msg: StateUpdateMessage<TWorldState>) => void>();
  private cursorUpdateHandlers = new Set<(msg: CursorUpdateMessage) => void>();
  private busMessageHandlers = new Set<(msg: BusMessageFrame) => void>();

  constructor(options: MivaisSocketOptions) {
    // Build with explicit fallbacks rather than `{...defaults, ...options}` —
    // a caller passing `host: undefined` (e.g. an unset optional prop) would
    // otherwise spread that `undefined` over the computed default.
    this.opts = {
      sessionId: options.sessionId,
      room: options.room ?? "default",
      role: options.role ?? "analyst",
      host: options.host ?? (typeof location !== "undefined" ? location.host || "localhost:8000" : "localhost:8000"),
      reconnectDelayMs: options.reconnectDelayMs ?? 3000,
      query: options.query ?? {},
    };
  }

  get status(): ConnectionStatus {
    if (!this.ws) return "connecting";
    return this.ws.readyState === WebSocket.OPEN ? "connected" : "connecting";
  }

  private buildUrl(): string {
    const wsProto = typeof location !== "undefined" && location.protocol === "https:" ? "wss:" : "ws:";
    const { host, sessionId, room, role, query } = this.opts;
    let url = `${wsProto}//${host}/ws/${sessionId}?room=${encodeURIComponent(room)}&role=${encodeURIComponent(role)}`;
    for (const [k, v] of Object.entries(query)) {
      if (k === "room" || k === "role" || v == null) continue;
      url += `&${encodeURIComponent(k)}=${encodeURIComponent(v)}`;
    }
    return url;
  }

  connect(): void {
    this.closedByUser = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    const ws = new WebSocket(this.buildUrl());
    this.ws = ws;

    ws.onopen = () => {
      this.openHandlers.forEach((h) => h());
    };
    ws.onclose = () => {
      this.closeHandlers.forEach((h) => h());
      if (!this.closedByUser) {
        this.reconnectTimer = setTimeout(() => this.connect(), this.opts.reconnectDelayMs);
      }
    };
    ws.onerror = () => {
      /* onclose fires next and drives the reconnect retry */
    };
    ws.onmessage = (ev) => {
      let msg: ServerMessage<TWorldState>;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      this.dispatch(msg);
    };
  }

  private dispatch(msg: ServerMessage<TWorldState>): void {
    switch (msg.type) {
      case "initial_state":
        this.initialStateHandlers.forEach((h) => h(msg));
        break;
      case "state_update":
        this.stateUpdateHandlers.forEach((h) => h(msg));
        break;
      case "cursor_update":
        this.cursorUpdateHandlers.forEach((h) => h(msg));
        break;
      case "bus_message":
        this.busMessageHandlers.forEach((h) => h(msg));
        break;
    }
  }

  /** Close and reopen the socket under a new role (e.g. a role-select change). */
  reconnectAs(role: string): void {
    this.opts.role = role;
    if (this.ws) this.ws.close();
    else this.connect();
  }

  disconnect(): void {
    this.closedByUser = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }

  send(action: BaseAction): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(action));
    }
  }

  onOpen(handler: () => void): Unsubscribe {
    this.openHandlers.add(handler);
    return () => this.openHandlers.delete(handler);
  }

  onClose(handler: () => void): Unsubscribe {
    this.closeHandlers.add(handler);
    return () => this.closeHandlers.delete(handler);
  }

  onInitialState(handler: (msg: InitialStateMessage<TWorldState>) => void): Unsubscribe {
    this.initialStateHandlers.add(handler);
    return () => this.initialStateHandlers.delete(handler);
  }

  onStateUpdate(handler: (msg: StateUpdateMessage<TWorldState>) => void): Unsubscribe {
    this.stateUpdateHandlers.add(handler);
    return () => this.stateUpdateHandlers.delete(handler);
  }

  onCursorUpdate(handler: (msg: CursorUpdateMessage) => void): Unsubscribe {
    this.cursorUpdateHandlers.add(handler);
    return () => this.cursorUpdateHandlers.delete(handler);
  }

  onBusMessage(handler: (msg: BusMessageFrame) => void): Unsubscribe {
    this.busMessageHandlers.add(handler);
    return () => this.busMessageHandlers.delete(handler);
  }
}
