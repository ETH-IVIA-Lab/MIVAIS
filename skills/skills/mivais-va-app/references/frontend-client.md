# `mivais-va-client` TypeScript API (`packages/mivais-va-client/src/*.ts`)

The frontend counterpart to the Gateway — your VA app's browser code uses this to talk
to *your own* backend's WebSocket, not to Studio. Studio observes your app through the
harness bridge (below), not by connecting to this client itself.

## Contents
- [Wire protocol (types.ts)](#wire-protocol-typests)
- [MivaisSocket (socket.ts)](#mivaissocket-socketts)
- [React integration (createMivaisContext.tsx)](#react-integration-createmivaiscontexttsx)
- [Harness — the Studio iframe bridge (harness.ts)](#harness--the-studio-iframe-bridge-harnessts)
- [REST helpers (rest.ts)](#rest-helpers-restts)

## Wire protocol (`types.ts`)

Server → client messages (`types.ts:63-104`):

```typescript
type ServerMessage<TWorldState> =
  | InitialStateMessage<TWorldState>   // type: "initial_state" — sent once on connect
  | StateUpdateMessage<TWorldState>    // type: "state_update" — every WorldState write
  | CursorUpdateMessage                // type: "cursor_update" — cursor/drag moves
  | BusMessageFrame;                   // type: "bus_message" — pub/sub delivery
```

`InitialStateMessage` (`types.ts:71-80`) carries the full snapshot plus everything a
client needs to bootstrap: `world_state`, `audit_log`, `cursors`, `connected_users`,
`my_permissions` (`{ role, can_write: string[], bus_publish_topics: string[] }`),
`chat_history`, `online_agents`.

Client → server: every outbound message is a `BaseAction` (`types.ts:108-111`):
```typescript
interface BaseAction { action: string; [key: string]: unknown; }
```

## MivaisSocket (`socket.ts`)

```typescript
new MivaisSocket({ sessionId, room?, role?, host?, reconnectDelayMs? })
```

Builds a URL of the form `{wsProto}://{host}/ws/{sessionId}?room={room}&role={role}`
(`socket.ts:66-69`) — `room` is what makes multi-room external apps addressable per
session; omit it for single-instance/spawned apps. Auto-reconnects on close with a
fixed delay (default 3000ms) unless you called `disconnect()` yourself
(`socket.ts:35-102`).

Handlers: `onOpen`, `onClose`, `onInitialState`, `onStateUpdate`, `onCursorUpdate`,
`onBusMessage` (`socket.ts:43-46, 144-172`). Send with `send(action: BaseAction)`
(`socket.ts:138-142`).

You rarely instantiate this directly in a React app — use the context provider below,
which wraps it.

## React integration (`createMivaisContext.tsx`)

Provider props (`createMivaisContext.tsx:17-31`):

| prop | purpose |
|---|---|
| `sessionId` | WebSocket session id |
| `room` | isolated world, defaults to `"default"` |
| `role` | permission level for this connection |
| `host` | backend host override |
| `harnessStripKeys` | state keys stripped before relaying to the parent frame (default `["dataset"]`) |

Context value (`createMivaisContext.tsx:33-53`): `connectionStatus`, `worldState`,
`auditLog`, `cursors`, `connectedUsers`, `onlineAgents`, `myPermissions`,
`chatHistory`, plus actions:

- `sendAction(action)` — send a typed action to the backend.
- `sendCursor(rowName?, x?, y?)` — deduplicated via `requestAnimationFrame`, safe to
  call on every `mousemove`.
- `sendChat(text, to?)`.
- `canWrite(key)` / `canPublish(topic)` — client-side gating for UI affordances (still
  enforced server-side too — don't skip that check just because the UI hides the
  button).
- `setRole(role)` — reconnect under a new role.
- `subscribeNewAuditEntries(cb)` — for activity animations/toasts on fresh audit
  entries.

A companion hook, `useCursorTracking.ts`, wires `sendCursor` to pointer events for you.

## Harness — the Studio iframe bridge (`harness.ts`)

This is what makes your app "just work" inside Studio's participant page and replay
viewer with zero Studio-specific code.

`relayToHarness(event)` (`harness.ts`) posts a message to the parent window:
`{ source: "mivais-va", kind: "va_event" | "agents", event/agents }` — `source` is
a constant protocol marker (`HARNESS_SOURCE`), not an app id. The React context
calls this automatically whenever:

- an agent acts → `{ type: "agent_action", actor, key, event_type, value_repr, accepted }`
- a user acts → `{ type: "user_action", action, data }`
- state updates → `{ type: "state_update", world_state: <stripped-of-harnessStripKeys> }`
- the agent roster changes → `relayAgentsRoster(agents)` (`harness.ts`)

If you're not React (e.g. vanilla JS like Starter_VA), call `relayToHarness` yourself at
the equivalent points, or skip it entirely if this app will only ever run standalone.

## REST helpers (`rest.ts`)

Thin fetch wrappers for the same-origin backend endpoints most apps expose alongside
the WebSocket (`rest.ts:27-59`), each accepting an optional `?room=<id>`:

- `/users` — role definitions
- `/audit` — audit log entries
- `/state` — full WorldState snapshot (this doubles as the health-check endpoint
  Studio's `health_check_url` typically points at)
- `/agents` — registered agents + capabilities
- `/recordings`, `/recordings/{filename}` — list/fetch JSONL recordings
