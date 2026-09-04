# BaseAgent

Abstract base class for all agents in MIVAIS. Provides access to `WorldState` and `MessageBus` through typed convenience helpers, and enforces the architectural contract that agents never hold references to each other.

## Constructor

```python
BaseAgent(
    agent_id: str,
    world_state: WorldState,
    message_bus: MessageBus,
    params: dict[str, Any] | None = None,
)
```

| Parameter | Type | Description |
|---|---|---|
| `agent_id` | `str` | Unique identifier, must match the `AgentRegistry` entry |
| `world_state` | `WorldState` | Shared blackboard |
| `message_bus` | `MessageBus` | Inter-agent message bus |
| `params` | `dict \| None` | Agent-specific configuration from the config file |

## Instance Attributes

| Attribute | Type | Description |
|---|---|---|
| `agent_id` | `str` | The agent's registered ID |
| `params` | `dict` | Agent-specific configuration parameters |

## Abstract Methods

### `run()` *(async, abstract)*

The agent's main observation loop. Must be implemented by every subclass.

```python
async def run(self) -> None:
    ...
```

Called once at startup as an asyncio task. Must run indefinitely — the task is cancelled on application shutdown, which raises `asyncio.CancelledError` inside `run()`.

**Responsibilities:**
1. Set up `watch()` callbacks on relevant WorldState keys.
2. Subscribe to relevant MessageBus topics if needed.
3. Wait for triggers (event-driven) or loop with `_sleep()` (poll-driven).
4. Handle exceptions internally — an unhandled exception silently kills the task.

## Optional Methods

### `on_message(message)` *(async)*

Called when a bus message arrives on a topic this agent has subscribed to via `_subscribe()`.

```python
async def on_message(self, message: dict) -> None:
    topic   = message["topic"]
    payload = message["payload"]
    sender  = message["sender"]
    # process the message
```

Default implementation is a no-op. Override to react to typed bus events.

| Parameter | Type | Description |
|---|---|---|
| `message` | `dict` | The full `BusMessage.to_dict()` payload |

## Convenience Methods

### `_read(key, default=None) → Any`

Read a key from WorldState.

```python
weights = self._read("weights", default={})
```

No permission check is applied on the read side.

---

### `_write(key, value) → bool`

Write a key to WorldState on behalf of this agent.

```python
accepted = self._write("result", {"score": 0.92})
```

`PermissionGuard` and `AuditLog` are invoked inside `WorldState.write()`. Returns `True` if the write was accepted.

---

### `_publish(topic, payload=None)` *(async)*

Publish a typed message on the MessageBus.

```python
await self._publish("ranking.ready", {"item_count": 406})
```

---

### `_subscribe(topic)`

Subscribe this agent to a MessageBus topic.

```python
self._subscribe("external.trigger")
```

Routes incoming messages to `self.on_message()`. Call at the start of `run()`.

---

### `_sleep(seconds)` *(async, static)*

Interruptible sleep for use in poll-driven agents.

```python
await self._sleep(5.0)
```

Raises `asyncio.CancelledError` when the asyncio task is cancelled at shutdown.

## Complete Example

```python
import asyncio
from typing import Any
from mivais import BaseAgent

class ScoreAdvisorAgent(BaseAgent):
    """
    Watches 'scores' in WorldState and publishes a textual summary
    on the 'advisor.insight' bus topic whenever scores change.
    """

    async def run(self) -> None:
        threshold = float(self.params.get("alert_threshold", 0.9))
        self._threshold = threshold
        self._ws.watch("scores", self._on_scores_changed)
        try:
            await asyncio.get_event_loop().create_future()
        except asyncio.CancelledError:
            pass

    async def _on_scores_changed(self, key: str, scores: Any) -> None:
        if not isinstance(scores, dict):
            return
        try:
            top = max(scores, key=scores.get)
            top_score = scores[top]
            summary = f"{top} leads with a score of {top_score:.2f}."
            if top_score > self._threshold:
                summary += f" Score exceeds alert threshold ({self._threshold})."
            await self._publish("advisor.insight", {
                "text": summary,
                "top_item": top,
                "top_score": top_score,
            })
        except Exception as exc:
            print(f"[{self.agent_id}] error in _on_scores_changed: {exc}")
```

## Architectural Contract

- Agents receive only `WorldState` and `MessageBus` at construction. Never inject other agents, the Gateway, or infrastructure objects.
- Use `_write()` rather than `self._ws.write()` directly — the helper fills in `self.agent_id` automatically.
- Do not call `system_write()` from agent code.
- All inter-agent communication goes through WorldState or MessageBus. Direct method calls between agents are not permitted.
