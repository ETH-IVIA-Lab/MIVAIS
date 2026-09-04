# PermissionGuard

Runtime enforcement of agent read and write boundaries. Every `WorldState.write()` call passes through this component. The Gateway uses it to filter per-agent snapshots and to validate user-initiated bus actions.

## Constructor

```python
PermissionGuard(registry: AgentRegistry)
```

| Parameter | Type | Description |
|---|---|---|
| `registry` | `AgentRegistry` | Source of declared capabilities for all agents |

## Methods

### `can_write(agent_id, key) → bool`

Return `True` if `agent_id` is permitted to write `key` to WorldState.

```python
if guard.can_write("ranker", "weights"):
    state._state["weights"] = value
```

Called automatically by `WorldState.write()`. You do not need to call this directly in agent code.

| Parameter | Type | Description |
|---|---|---|
| `agent_id` | `str` | The agent attempting the write |
| `key` | `str` | The WorldState key being written |

**Returns:** `bool`

**Rules:**
- Agent not registered → `False`
- `can_write` is empty → `False` (restrictive default)
- `key` is in `can_write` → `True`
- Otherwise → `False`

---

### `readable_keys(agent_id, all_keys) → list[str]`

Filter `all_keys` to the subset the agent is permitted to read.

```python
visible_keys = guard.readable_keys("user:abc", list(state._state.keys()))
```

Called by `WorldState.snapshot_for()`.

| Parameter | Type | Description |
|---|---|---|
| `agent_id` | `str` | The agent requesting the filtered view |
| `all_keys` | `list[str]` | All currently present WorldState keys |

**Returns:** `list[str]`

**Rules:**
- Agent not registered → `[]`
- `can_read` is empty → all keys returned (permissive default)
- Otherwise → only keys present in `can_read`

---

### `can_publish(agent_id, topic) → bool`

Return `True` if `agent_id` may publish on `topic` via the MessageBus.

```python
if guard.can_publish("user:abc", "nl_command.request"):
    await bus.publish(agent_id, "nl_command.request", payload)
```

Used by the Gateway when routing a user-initiated `publish_bus` action. Not called by `MessageBus.publish()` itself.

| Parameter | Type | Description |
|---|---|---|
| `agent_id` | `str` | The agent attempting to publish |
| `topic` | `str` | The topic being published on |

**Returns:** `bool`

**Rules:**
- Agent not registered → `False`
- `bus_publish_topics` is empty → `True` (permissive default for agents)
- `topic` is in `bus_publish_topics` → `True`
- Otherwise → `False`

---

### `can_subscribe(agent_id, topic) → bool`

Return `True` if `agent_id` may subscribe to `topic` on the MessageBus.

```python
if guard.can_subscribe("user:abc", "advisor.insight"):
    bus.subscribe(agent_id, topic, handler)
```

| Parameter | Type | Description |
|---|---|---|
| `agent_id` | `str` | The agent attempting to subscribe |
| `topic` | `str` | The topic being subscribed to |

**Returns:** `bool`

**Rules:**
- Agent not registered → `False`
- `bus_subscribe_topics` is empty → `True` (permissive default for agents)
- `topic` is in `bus_subscribe_topics` → `True`
- Otherwise → `False`

## Permission Model Summary

| Condition | Effect |
|---|---|
| `can_read: []` | Read all WorldState keys |
| `can_read: ["a", "b"]` | Read only keys `a` and `b` |
| `can_write: []` | Write nothing (denied) |
| `can_write: ["x"]` | Write only key `x` |
| `bus_publish_topics: []` | Publish on any topic |
| `bus_publish_topics: ["t"]` | Publish only on topic `t` |
| `bus_subscribe_topics: []` | Subscribe to any topic |
| `bus_subscribe_topics: ["t"]` | Subscribe only to topic `t` |

The asymmetry between reads and writes (`[]` means "all" for reads but "nothing" for writes) is intentional. Write access is the primary security boundary. Read access is generally safe.
