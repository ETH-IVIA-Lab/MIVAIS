# Configuration

MIVAIS applications are configured through a single JSON file, conventionally named `agents_config.yaml`. This file is the canonical declaration of all permissions and agent capabilities. No permissions are hardcoded in Python.

::: tip Formal grammars
Formal EBNF grammars for all four configuration languages — `agents_config.yaml`, `mivais_config.yaml`, study definitions, and task definitions — live in [Configuration Grammars (EBNF)](/reference/grammars).
:::

## Structure

```yaml
users:
  <role_name>: { ... }
agents:
  - { ... }
```

## User Roles

Each key under `"users"` defines a role. When a client connects via WebSocket with `?role=analyst`, the Gateway looks up `"analyst"` here, creates an `AgentCapabilities` entry, and registers the user as an agent.

```yaml
users:
  analyst:
    description: Full read/write access
    can_read: []
    can_write:
    - filter_criteria
    - display_order
    bus_publish_topics:
    - chat.message
    bus_subscribe_topics:
    - chat.message
    - summary.update
  observer:
    description: Read-only, receives updates
    can_read: []
    can_write: []
    bus_publish_topics: []
    bus_subscribe_topics:
    - summary.update
```

### User Role Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `description` | string | `""` | Label shown in topology views |
| `can_read` | string[] | `[]` | Keys this role may read. Empty → read all |
| `can_write` | string[] | `[]` | Keys this role may write. Empty → write nothing |
| `bus_publish_topics` | string[] | `[]` | Topics the user may publish on via the Gateway |
| `bus_subscribe_topics` | string[] | `[]` | Topics delivered to this role's WebSocket connection |

## Agents

Each object in the `"agents"` array configures one autonomous agent.

```yaml
agents:
- agent_id: scoring_agent
  role: processor
  description: Computes scores from user preferences
  enabled: true
  class: agents.scoring_agent.ScoringAgent
  trigger: watch
  can_read:
  - dataset
  - filter_criteria
  can_write:
  - scores
  - agent_status
  bus_publish_topics:
  - scoring.done
  bus_subscribe_topics: []
  params:
    threshold: 0.5
```

### Agent Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `agent_id` | string | required | Unique identifier. Used in audit log and registry lookups |
| `role` | string | required | Human-readable role label |
| `description` | string | `""` | Description shown in topology views |
| `enabled` | boolean | `true` | Skip this agent at startup if `false` |
| `class` | string | required | Fully qualified Python class path: `"package.module.ClassName"` |
| `trigger` | `"watch"` \| `"poll"` | `"watch"` | Observation strategy |
| `poll_interval_seconds` | number | `null` | Polling interval when `trigger="poll"` |
| `can_read` | string[] | `[]` | Keys this agent may read. Empty → read all |
| `can_write` | string[] | `[]` | Keys this agent may write. Empty → write nothing |
| `bus_publish_topics` | string[] | `[]` | Topics this agent may publish on. Empty → all topics |
| `bus_subscribe_topics` | string[] | `[]` | Topics this agent subscribes to at startup |
| `params` | object | `{}` | Arbitrary parameters passed to the agent constructor as `self.params` |

## Loading Configuration

The standard startup pattern reads the config file and registers each agent:

```python
import importlib, json
from pathlib import Path
from mivais import AgentCapabilities

config = json.loads(Path("agents_config.yaml").read_text(encoding="utf-8"))

for agent_cfg in config["agents"]:
    if not agent_cfg.get("enabled", True):
        continue

    module_path, class_name = agent_cfg["class"].rsplit(".", 1)
    AgentClass = getattr(importlib.import_module(module_path), class_name)

    caps = AgentCapabilities(
        agent_id             = agent_cfg["agent_id"],
        role                 = agent_cfg["role"],
        description          = agent_cfg.get("description", ""),
        can_read             = agent_cfg.get("can_read", []),
        can_write            = agent_cfg.get("can_write", []),
        bus_publish_topics   = agent_cfg.get("bus_publish_topics", []),
        bus_subscribe_topics = agent_cfg.get("bus_subscribe_topics", []),
        params               = agent_cfg.get("params", {}),
    )
    instance = AgentClass(caps.agent_id, state, bus, caps.params)
    registry.register(caps, instance)
    asyncio.create_task(instance.run())
```

## Permission Model Quick Reference

| Configured value | Effect |
|---|---|
| `can_read: []` | Read all WorldState keys |
| `can_read: ["a", "b"]` | Read only keys `a` and `b` |
| `can_write: []` | Write nothing |
| `can_write: ["x"]` | Write only key `x` |
| `bus_publish_topics: []` | Publish on all topics (agent code only) |
| `bus_publish_topics: ["t"]` | Publish only on topic `t` |
| `bus_subscribe_topics: []` | No topics forwarded via Gateway |
| `bus_subscribe_topics: ["t"]` | Topic `t` delivered to this client |

::: warning
`can_write: []` means **write nothing**, not write everything. This is the restrictive default. Explicitly list every key an agent or role needs to write.
:::

## Hot Reloading User Roles

User role definitions can be reloaded at runtime without restarting the server. This does not restart agents — it only affects the permissions of users who connect after the reload.

```python
from watchfiles import awatch

async def watch_config(gateway, config_path):
    async for _ in awatch(config_path):
        try:
            config = json.loads(Path(config_path).read_text(encoding="utf-8"))
            gateway.reload_user_configs(config["users"])
            print("[config] user roles reloaded")
        except Exception as exc:
            print(f"[config] reload failed: {exc}")
```
