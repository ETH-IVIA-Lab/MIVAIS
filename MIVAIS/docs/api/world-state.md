# WorldState

The central shared blackboard. Every piece of data shared between participants in a MIVAIS application lives here. Agents and the Gateway read and write exclusively through this object — they never hold references to each other.

## Constructor

```python
WorldState(audit_log: AuditLog, permission_guard: PermissionGuard)
```

| Parameter | Type | Description |
|---|---|---|
| `audit_log` | `AuditLog` | Records every write attempt |
| `permission_guard` | `PermissionGuard` | Enforces write permissions |

## Methods

### `get(key, default=None)`

Read the current value of a key.

```python
value = state.get("weights", default={})
```

No permission check is applied. Any code with a reference to the WorldState can call this.

| Parameter | Type | Description |
|---|---|---|
| `key` | `str` | The key to read |
| `default` | `Any` | Returned if the key is not present |

**Returns:** `Any`

---

### `snapshot()`

Return a full copy of the current state as a plain dict.

```python
full_state = state.snapshot()
```

Used by the Gateway to construct WebSocket payloads. No permission filtering.

**Returns:** `dict[str, Any]`

---

### `snapshot_for(agent_id)`

Return a permission-filtered copy of the current state.

```python
agent_view = state.snapshot_for("user:abc123")
```

Only keys listed in the agent's `can_read` are included. If `can_read` is empty, all keys are returned.

| Parameter | Type | Description |
|---|---|---|
| `agent_id` | `str` | The agent whose read permissions are applied |

**Returns:** `dict[str, Any]`

---

### `write(agent_id, key, value, event_type="write")`

Write a value on behalf of `agent_id`.

```python
accepted = state.write("ranker_agent", "weights", {"mpg": 0.6, "hp": 0.4})
```

**Steps:**
1. `PermissionGuard.can_write(agent_id, key)` — deny immediately if not authorised.
2. `AuditLog.record(...)` with `accepted=True` or `accepted=False`.
3. Apply the write to the internal dict.
4. Schedule watcher notifications as a non-blocking asyncio task.

| Parameter | Type | Description |
|---|---|---|
| `agent_id` | `str` | The agent performing the write |
| `key` | `str` | The key to write |
| `value` | `Any` | The value to store |
| `event_type` | `str` | Audit log label. Use `"user_input"` for user-initiated writes |

**Returns:** `bool` — `True` if the write was accepted, `False` if denied.

---

### `system_write(key, value)`

Infrastructure-level write that bypasses permission checks.

```python
state.system_write("dataset", records)
```

Use this only at startup (loading initial data) or in Gateway infrastructure code. Always logged with `actor="system"`.

::: warning
Do not call `system_write` from agent code. Use `write()` with a declared `agent_id` so the permission model is enforced and the write is attributed correctly.
:::

| Parameter | Type | Description |
|---|---|---|
| `key` | `str` | The key to write |
| `value` | `Any` | The value to store |

---

### `watch(key, callback)`

Register an async callback that fires whenever `key` is written.

```python
async def on_weights_changed(key: str, value: Any) -> None:
    ...

state.watch("weights", on_weights_changed)
```

Multiple callbacks may be registered for the same key. All are called in registration order. Callbacks are called after every *accepted* write (permission-checked writes that returned `True`).

| Parameter | Type | Description |
|---|---|---|
| `key` | `str` | The key to observe |
| `callback` | `Callable[[str, Any], Awaitable[None]]` | Async function receiving `(key, value)` |

---

### `watch_any(callback)`

Register an async callback that fires on every write of any key.

```python
state.watch_any(gateway._on_state_changed)
```

Used internally by the Gateway to push state updates to clients. Prefer `watch(key, ...)` in agents to avoid unnecessary processing.

| Parameter | Type | Description |
|---|---|---|
| `callback` | `Callable[[str, Any], Awaitable[None]]` | Async function receiving `(key, value)` |

## Design Notes

**No agent references.** The WorldState holds no references to agent instances. Notification happens through registered callbacks, not method calls.

**Watcher error isolation.** If a watcher callback raises, the error is printed and other watchers continue to fire. A misbehaving agent cannot break the notification chain.

**Notification is non-blocking.** Watcher notifications are scheduled as asyncio tasks via `loop.create_task()`. The `write()` call returns immediately; watchers fire on the next event loop iteration.
