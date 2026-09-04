import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { MivaisSocket } from "../socket.js";
import { relayToHarness, relayAgentsRoster } from "../harness.js";
import type {
  AuditEntry,
  BaseAction,
  ChatPayload,
  ConnectedUser,
  ConnectionStatus,
  CursorMap,
  OnlineAgent,
  Permissions,
} from "../types.js";

export interface MivaisProviderProps {
  /** Unique id for this WebSocket connection (path segment `/ws/{sessionId}`). */
  sessionId: string;
  /** Isolated world to join. Defaults to `"default"`. */
  room?: string;
  /** Permission role to connect as. */
  role: string;
  /** Host override, e.g. for a dev-server proxy target. Defaults to `location.host`. */
  host?: string;
  /** Extra query params appended to the WS URL (see MivaisSocketOptions.query). */
  wsQuery?: Record<string, string>;
  /** World-state keys stripped before relaying `state_update` to the harness (bandwidth). */
  harnessStripKeys?: string[];
  children: ReactNode;
}

export interface MivaisContextValue<TWorldState, TAction extends BaseAction> {
  connectionStatus: ConnectionStatus;
  worldState: Partial<TWorldState>;
  auditLog: AuditEntry[];
  cursors: CursorMap;
  connectedUsers: ConnectedUser[];
  onlineAgents: OnlineAgent[];
  myPermissions: Permissions;
  chatHistory: ChatPayload[];
  role: string;
  sessionId: string;
  sendAction: (action: TAction) => void;
  /** `rowName` omitted (undefined) preserves the row currently attributed server-side; pass `null` to explicitly clear it. */
  sendCursor: (rowName?: string | null, x?: number | null, y?: number | null) => void;
  sendChat: (text: string, to?: string) => void;
  canWrite: (key: string) => boolean;
  canPublish: (topic: string) => boolean;
  setRole: (role: string) => void;
  /** Subscribe to just the audit entries that are new-since-last-message (for activity animations). */
  subscribeNewAuditEntries: (cb: (entries: AuditEntry[]) => void) => () => void;
}

const EMPTY_PERMISSIONS: Permissions = { role: "", can_write: [], bus_publish_topics: [] };

function extractChatPayload(entry: { payload?: ChatPayload } & Partial<ChatPayload>): ChatPayload {
  return (entry.payload ?? entry) as ChatPayload;
}

/**
 * Builds a typed `{ MivaisProvider, useMivais }` pair bound to one app's
 * WorldState/action shape. Each MIVAIS-based app calls this once so `sendAction`/`worldState` are
 * fully typed while the connection/protocol logic is shared.
 */
export function createMivaisContext<
  TWorldState = Record<string, unknown>,
  TAction extends BaseAction = BaseAction,
>() {
  const Context = createContext<MivaisContextValue<TWorldState, TAction> | null>(null);

  function MivaisProvider({
    sessionId,
    room = "default",
    role,
    host,
    wsQuery,
    harnessStripKeys = ["dataset"],
    children,
  }: MivaisProviderProps) {
    // Content signature so a new-but-equal object literal doesn't reconnect.
    const wsQuerySig = JSON.stringify(wsQuery ?? {});
    const socketRef = useRef<MivaisSocket<TWorldState> | null>(null);
    const seenAuditIds = useRef<Set<string>>(new Set());
    const newAuditListeners = useRef<Set<(entries: AuditEntry[]) => void>>(new Set());
    const pendingCursor = useRef<{ row_name?: string | null; x?: number | null; y?: number | null } | null>(null);
    const cursorRaf = useRef<number | null>(null);

    const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("connecting");
    const [worldState, setWorldState] = useState<Partial<TWorldState>>({});
    const [auditLog, setAuditLog] = useState<AuditEntry[]>([]);
    const [cursors, setCursors] = useState<CursorMap>({});
    const [connectedUsers, setConnectedUsers] = useState<ConnectedUser[]>([]);
    const [onlineAgents, setOnlineAgents] = useState<OnlineAgent[]>([]);
    const [myPermissions, setMyPermissions] = useState<Permissions>(EMPTY_PERMISSIONS);
    const [chatHistory, setChatHistory] = useState<ChatPayload[]>([]);
    const [currentRole, setCurrentRole] = useState(role);

    const applyAuditLog = useCallback(
      (entries: AuditEntry[]) => {
        setAuditLog(entries);
        const fresh = entries.filter((e) => !seenAuditIds.current.has(e.id));
        fresh.forEach((e) => seenAuditIds.current.add(e.id));
        if (fresh.length) {
          newAuditListeners.current.forEach((cb) => cb(fresh));
          fresh.forEach((e) => {
            if (e.actor && !e.actor.startsWith("user:") && e.event_type !== "cursor_move") {
              relayToHarness({
                type: "agent_action",
                actor: e.actor,
                key: e.key,
                event_type: e.event_type,
                value_repr: e.value_repr,
                accepted: e.accepted,
              });
            }
          });
        }
      },
      [],
    );

    useEffect(() => {
      const socket = new MivaisSocket<TWorldState>({ sessionId, room, role, host, query: wsQuery });
      socketRef.current = socket;

      const unsubs = [
        socket.onOpen(() => setConnectionStatus("connected")),
        socket.onClose(() => setConnectionStatus("reconnecting")),
        socket.onInitialState((msg) => {
          setMyPermissions(msg.my_permissions ?? EMPTY_PERMISSIONS);
          setChatHistory((msg.chat_history ?? []).map(extractChatPayload));
          setWorldState(msg.world_state ?? {});
          setCursors(msg.cursors ?? {});
          setConnectedUsers(msg.connected_users ?? []);
          setOnlineAgents(msg.online_agents ?? []);
          relayAgentsRoster(msg.online_agents ?? []);
          applyAuditLog(msg.audit_log ?? []);
        }),
        socket.onStateUpdate((msg) => {
          if (msg.world_state) setWorldState((prev) => ({ ...prev, ...msg.world_state }));
          if (msg.cursors !== undefined) setCursors(msg.cursors);
          if (msg.connected_users !== undefined) setConnectedUsers(msg.connected_users);
          if (msg.online_agents !== undefined) {
            setOnlineAgents(msg.online_agents);
            relayAgentsRoster(msg.online_agents);
          }
          if (msg.audit_log) applyAuditLog(msg.audit_log);
        }),
        socket.onCursorUpdate((msg) => {
          setCursors(msg.cursors ?? {});
          setConnectedUsers(msg.connected_users ?? []);
        }),
        socket.onBusMessage((msg) => {
          const m = msg.message;
          if (m?.topic === "chat.message" && m.payload) {
            setChatHistory((prev) => [...prev, m.payload as ChatPayload]);
          }
        }),
      ];

      socket.connect();

      return () => {
        unsubs.forEach((u) => u());
        socket.disconnect();
        socketRef.current = null;
      };
      // Intentionally reconnect only when identity/target changes, not on every render.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [sessionId, room, host, wsQuerySig, applyAuditLog]);

    // Relay a slimmed state_update to the embedding harness whenever worldState changes
    // (covers both the initial snapshot and every subsequent broadcast uniformly).
    useEffect(() => {
      if (!Object.keys(worldState).length) return;
      const slim = { ...(worldState as Record<string, unknown>) };
      harnessStripKeys.forEach((k) => delete slim[k]);
      relayToHarness({ type: "state_update", world_state: slim });
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [worldState]);

    const sendAction = useCallback(
      (action: TAction) => {
        socketRef.current?.send(action);
        relayToHarness({ type: "user_action", action: action.action, data: action });
      },
      [],
    );

    const sendCursor = useCallback((rowName?: string | null, x?: number | null, y?: number | null) => {
      pendingCursor.current = { row_name: rowName, x, y };
      if (cursorRaf.current !== null) return;
      cursorRaf.current = requestAnimationFrame(() => {
        if (pendingCursor.current) {
          socketRef.current?.send({ action: "cursor_move", ...pendingCursor.current });
        }
        cursorRaf.current = null;
      });
    }, []);

    const sendChat = useCallback((text: string, to = "broadcast") => {
      if (!text.trim()) return;
      socketRef.current?.send({ action: "chat_message", to, text });
    }, []);

    const canWrite = useCallback((key: string) => myPermissions.can_write.includes(key), [myPermissions]);
    const canPublish = useCallback(
      (topic: string) => myPermissions.bus_publish_topics.includes(topic),
      [myPermissions],
    );

    const setRole = useCallback((newRole: string) => {
      setCurrentRole(newRole);
      setConnectionStatus("reconnecting");
      socketRef.current?.reconnectAs(newRole);
    }, []);

    const subscribeNewAuditEntries = useCallback((cb: (entries: AuditEntry[]) => void) => {
      newAuditListeners.current.add(cb);
      return () => newAuditListeners.current.delete(cb);
    }, []);

    const value = useMemo<MivaisContextValue<TWorldState, TAction>>(
      () => ({
        connectionStatus,
        worldState,
        auditLog,
        cursors,
        connectedUsers,
        onlineAgents,
        myPermissions,
        chatHistory,
        role: currentRole,
        sessionId,
        sendAction,
        sendCursor,
        sendChat,
        canWrite,
        canPublish,
        setRole,
        subscribeNewAuditEntries,
      }),
      [
        connectionStatus,
        worldState,
        auditLog,
        cursors,
        connectedUsers,
        onlineAgents,
        myPermissions,
        chatHistory,
        currentRole,
        sessionId,
        sendAction,
        sendCursor,
        sendChat,
        canWrite,
        canPublish,
        setRole,
        subscribeNewAuditEntries,
      ],
    );

    return <Context.Provider value={value}>{children}</Context.Provider>;
  }

  function useMivais(): MivaisContextValue<TWorldState, TAction> {
    const ctx = useContext(Context);
    if (!ctx) throw new Error("useMivais must be used within its matching MivaisProvider");
    return ctx;
  }

  return { MivaisProvider, useMivais };
}
