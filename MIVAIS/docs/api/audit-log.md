# AuditLog

Immutable append-only provenance record. Every write attempt to WorldState — whether accepted or denied — and every message published on the MessageBus is recorded here. Entries are never removed.

## Constructor

```python
AuditLog()
```

No dependencies.

## Classes

### `AuditEntry`

A single record in the audit log.

```python
class AuditEntry:
    id: str           # UUID
    timestamp: str    # ISO 8601 UTC
    actor: str        # agent_id performing the action
    key: str          # WorldState key, or "bus:<topic>" for bus messages
    value_repr: str   # repr() of the value, truncated to 150 characters
    accepted: bool    # True if the write was permitted, False if denied
    event_type: str   # "write" | "denied" | "bus_message" | "user_input" | "cursor_move"
```

#### `to_dict() → dict`

Returns the entry as a JSON-serialisable dict.

## Methods

### `record(actor, key, value=None, accepted=True, event_type="write") → AuditEntry`

Record a WorldState write attempt.

```python
audit.record(
    actor="ranker",
    key="weights",
    value={"mpg": 0.6},
    accepted=True,
    event_type="write",
)
```

Called automatically by `WorldState.write()` and `WorldState.system_write()`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `actor` | `str` | required | The agent performing the action |
| `key` | `str` | required | The WorldState key |
| `value` | `Any` | `None` | The value being written (stored as `repr()`, truncated) |
| `accepted` | `bool` | `True` | Whether the write was permitted |
| `event_type` | `str` | `"write"` | Label for the event |

**Returns:** `AuditEntry`

---

### `record_bus_message(sender, topic, payload=None) → AuditEntry`

Record an inter-agent message on the MessageBus.

```python
audit.record_bus_message(
    sender="ranker",
    topic="ranking.ready",
    payload={"item_count": 406},
)
```

Called automatically by `MessageBus.publish()`.

The `key` field of the resulting entry will be `"bus:<topic>"`.

| Parameter | Type | Description |
|---|---|---|
| `sender` | `str` | The publishing agent's ID |
| `topic` | `str` | The topic the message was published on |
| `payload` | `Any` | The message payload (stored as `repr()`, truncated) |

**Returns:** `AuditEntry`

---

### `get_entries(limit=100) → list[dict]`

Return the last `limit` entries as JSON-serialisable dicts.

```python
tail = audit.get_entries(limit=60)
```

Used by the Gateway to include the audit tail in every state update pushed to clients.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | `int` | `100` | Maximum number of entries to return |

**Returns:** `list[dict]`

---

### `get_all() → list[dict]`

Return every entry as JSON-serialisable dicts.

```python
@app.get("/audit")
def get_audit():
    return audit.get_all()
```

**Returns:** `list[dict]`

---

### `__len__() → int`

Return the total number of recorded entries.

```python
print(f"Session produced {len(audit)} audit entries")
```

## Event Types

| `event_type` | Written by | Meaning |
|---|---|---|
| `write` | WorldState (accepted), system_write | Accepted write to WorldState |
| `denied` | WorldState (rejected) | Write denied by PermissionGuard |
| `bus_message` | MessageBus | Message published on a topic |
| `user_input` | Gateway | Write initiated by a user action |
| `cursor_move` | Gateway | User cursor moved to a new row |

## Design Notes

**No clear method.** The AuditLog has no way to delete or modify entries. This is intentional — the log is a provenance record, not a cache.

**Value truncation.** Values are stored as `repr()` strings, truncated to 150 characters. The audit log is not designed to reconstruct state — use `SessionRecorder` for full state replay.

**Denied writes are logged.** A denied write still produces an audit entry with `accepted=False`. This makes it possible to detect and investigate permission violations.
