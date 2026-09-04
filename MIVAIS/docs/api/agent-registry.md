# AgentRegistry

Single source of truth for registered agents and their capabilities. Populated from configuration at startup and dynamically updated when users connect and disconnect. The `PermissionGuard` consults this registry on every write and topic access.

## Constructor

```python
AgentRegistry()
```

No dependencies.

## Classes

### `AgentCapabilities`

Dataclass containing everything the infrastructure needs to know about an agent.

```python
@dataclass
class AgentCapabilities:
    agent_id: str
    role: str
    description: str = ""
    can_read: list[str] = field(default_factory=list)
    can_write: list[str] = field(default_factory=list)
    bus_publish_topics: list[str] = field(default_factory=list)
    bus_subscribe_topics: list[str] = field(default_factory=list)
    trigger: str = "watch"
    poll_interval_seconds: float | None = None
    params: dict[str, Any] = field(default_factory=dict)
```

#### Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `agent_id` | `str` | required | Unique identifier. `user:<session_id>` for connected users |
| `role` | `str` | required | Human-readable role label (e.g. `"analyst"`, `"processor"`) |
| `description` | `str` | `""` | Optional description for topology views |
| `can_read` | `list[str]` | `[]` | WorldState keys this agent may read. Empty → read all |
| `can_write` | `list[str]` | `[]` | WorldState keys this agent may write. Empty → write nothing |
| `bus_publish_topics` | `list[str]` | `[]` | Topics this agent may publish on. Empty → all topics |
| `bus_subscribe_topics` | `list[str]` | `[]` | Topics forwarded to this agent via the Gateway |
| `trigger` | `str` | `"watch"` | `"watch"` (event-driven) or `"poll"` (time-driven) |
| `poll_interval_seconds` | `float \| None` | `None` | Polling interval when `trigger="poll"` |
| `params` | `dict` | `{}` | Arbitrary agent-specific parameters |

## Methods

### `register(capabilities, instance)`

Register an agent with its capabilities and running instance.

```python
agent = MyAgent("ranker", state, bus, params={})
registry.register(caps, agent)
```

Called at startup after an agent is instantiated and before its `run()` coroutine is started.

| Parameter | Type | Description |
|---|---|---|
| `capabilities` | `AgentCapabilities` | The agent's declared permissions and metadata |
| `instance` | `BaseAgent` | The running agent instance |

---

### `register_dynamic(capabilities)`

Register an agent at runtime without a running instance.

```python
registry.register_dynamic(AgentCapabilities(
    agent_id="user:abc123",
    role="analyst",
    can_write=["user_input"],
))
```

Used by the Gateway when a user connects. The user has no `run()` coroutine — the Gateway handles their interaction.

| Parameter | Type | Description |
|---|---|---|
| `capabilities` | `AgentCapabilities` | The agent's declared permissions |

---

### `deregister(agent_id)`

Remove a dynamically registered agent.

```python
registry.deregister("user:abc123")
```

Called by the Gateway when a user disconnects. After deregistration, any write attempt by that `agent_id` will be denied.

| Parameter | Type | Description |
|---|---|---|
| `agent_id` | `str` | The agent to remove |

---

### `get(agent_id) → AgentCapabilities | None`

Return the capabilities for an agent, or `None` if not registered.

```python
caps = registry.get("ranker")
if caps:
    print(caps.can_write)
```

**Returns:** `AgentCapabilities | None`

---

### `get_instance(agent_id) → Any | None`

Return the running agent instance, or `None`.

```python
agent = registry.get_instance("ranker")
```

**Returns:** `BaseAgent | None`

---

### `all_ids() → list[str]`

Return all registered agent IDs.

**Returns:** `list[str]`

---

### `summary() → list[dict]`

Return a JSON-serialisable summary of all registered agents and their capabilities.

```python
@app.get("/agents")
def get_agents():
    return registry.summary()
```

Each entry includes: `agent_id`, `role`, `description`, `can_read`, `can_write`, `trigger`, `poll_interval_seconds`, `bus_publish_topics`, `bus_subscribe_topics`.

**Returns:** `list[dict]`
