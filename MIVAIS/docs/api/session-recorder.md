# SessionRecorder

Writes a timestamped JSONL recording of every event in a MIVAIS session. Each line is one JSON object, parseable independently. Recordings can be replayed frame by frame or seeked to any point in time.

## Constructor

```python
SessionRecorder(recordings_dir: Path)
```

Creates a new recording file in `recordings_dir` named `session_YYYYMMDD_HHMMSS.jsonl`. The directory is created if it does not exist.

| Parameter | Type | Description |
|---|---|---|
| `recordings_dir` | `Path` | Directory where recording files are written |

## Class Attributes

### `CURSOR_MIN_INTERVAL_MS`

Minimum interval between cursor snapshot recordings, in milliseconds.

```python
CURSOR_MIN_INTERVAL_MS: float = 50.0  # 20 fps maximum
```

Cursor events are the highest-frequency events in a session. This throttle prevents recording files from becoming excessively large.

## Methods

### `record(event_type, data)`

Append one event to the recording file.

```python
recorder.record("connect", {"session_id": "abc123", "role": "analyst"})
```

Every event is stored as:
```json
{"t": 4821, "type": "connect", "session_id": "abc123", "role": "analyst"}
```

where `t` is milliseconds elapsed since the recorder was constructed.

| Parameter | Type | Description |
|---|---|---|
| `event_type` | `str` | Event type label |
| `data` | `dict` | Event payload merged into the record |

---

### `record_cursors(cursors, connected_users)`

Throttled cursor snapshot. Skipped if called within `CURSOR_MIN_INTERVAL_MS` of the last call.

```python
recorder.record_cursors(gateway._cursors, gateway._presence_list())
```

| Parameter | Type | Description |
|---|---|---|
| `cursors` | `dict` | Current cursor state by agent_id |
| `connected_users` | `list` | Current presence list |

---

### `record_state(world_state, audit_log, cursors, connected_users, *, full_snapshot=False)`

Record a WorldState broadcast.

```python
# Full snapshot (once at startup, includes all keys)
recorder.record_state(snapshot, audit_tail, cursors, presence, full_snapshot=True)

# Incremental update
recorder.record_state(snapshot_safe, audit_tail, cursors, presence)
```

When `full_snapshot=True`, the event type is `"snapshot"`. Otherwise it is `"state_update"`.

| Parameter | Type | Description |
|---|---|---|
| `world_state` | `dict` | The state dict to record |
| `audit_log` | `list` | The audit tail to record |
| `cursors` | `dict` | Current cursor state |
| `connected_users` | `list` | Current presence list |
| `full_snapshot` | `bool` | If `True`, records as `"snapshot"` event type |

---

### `close()`

Flush and close the recording file.

```python
recorder.close()
```

Call this during application shutdown to ensure the file is properly closed.

## Properties

### `filename → str`

Base filename of the current recording (e.g. `session_20250401_143022.jsonl`).

### `path → Path`

Absolute path to the current recording file.

## Event Types

| `type` | Description |
|---|---|
| `snapshot` | Full initial state including all keys (written once per session) |
| `state_update` | WorldState broadcast, may exclude large keys |
| `cursor_update` | Throttled cursor snapshot |
| `connect` | User connected: `{session_id, role}` |
| `disconnect` | User disconnected: `{session_id}` |
| `bus_message` | Bus message: `{sender, topic, payload}` |
| `user_action` | User input action: `{actor, action, data}` |

## JSONL Format

Each line is a self-contained JSON object:

```jsonl
{"t":0,"type":"snapshot","world_state":{...},"audit_log":[...],"cursors":{},"connected_users":[]}
{"t":142,"type":"connect","session_id":"abc123","role":"analyst"}
{"t":312,"type":"user_action","actor":"user:abc123","action":"submit_ranking","data":{"ranking":[2,0,1]}}
{"t":318,"type":"state_update","world_state":{...},"audit_log":[...],"cursors":{},"connected_users":[...]}
{"t":420,"type":"cursor_update","cursors":{"user:abc123":{"x":0.4,"y":0.6}},"connected_users":[...]}
{"t":8041,"type":"disconnect","session_id":"abc123"}
```

This format is designed for efficient replay:
- To find the state at time `T`: scan backwards from `T` to find the last `state_update` or `snapshot`, then forward-apply all `user_action` events up to `T`.
- Each line can be parsed with `json.loads()` independently.
- The `t` field is always relative to the recorder's construction time, not wall-clock time.
