# MessageBus

Typed async publish/subscribe channel for inter-agent communication. Agents publish messages on named topics; other agents subscribe to topics and receive messages asynchronously. No agent needs to know which other agents are subscribed.

## Constructor

```python
MessageBus(audit_log: AuditLog)
```

| Parameter | Type | Description |
|---|---|---|
| `audit_log` | `AuditLog` | Every published message is recorded here |

## Classes

### `BusMessage`

A single typed message on the bus.

```python
@dataclass
class BusMessage:
    id: str           # UUID
    timestamp: str    # ISO 8601 UTC
    sender: str       # agent_id of the publisher
    topic: str        # the topic it was published on
    payload: dict     # arbitrary JSON-serialisable payload
```

#### `to_dict() → dict`

Returns the message as a JSON-serialisable dict.

## Methods

### `subscribe(agent_id, topic, handler)`

Register `agent_id` as a subscriber to `topic`.

```python
bus.subscribe("advisor", "ranking.ready", advisor.on_message)
```

When a message is published on `topic`, `handler` is called asynchronously with the message dict.

| Parameter | Type | Description |
|---|---|---|
| `agent_id` | `str` | Identifier of the subscribing agent |
| `topic` | `str` | Topic to subscribe to |
| `handler` | `Callable[[dict], Awaitable[None]]` | Async function called with the message dict |

::: tip
In a `BaseAgent` subclass, use `self._subscribe(topic)` instead. It automatically routes messages to `self.on_message()`.
:::

---

### `publish(sender, topic, payload=None)` *(async)*

Publish a typed message on `topic`.

```python
await bus.publish("ranker", "ranking.ready", {"item_count": 406})
```

**Steps:**
1. Construct a `BusMessage` with a UUID and UTC timestamp.
2. Record to `AuditLog` with `event_type="bus_message"`.
3. Async-deliver to all subscribers of `topic` as independent asyncio tasks.

Delivery is fire-and-forget. The publisher does not await subscriber completion.

| Parameter | Type | Description |
|---|---|---|
| `sender` | `str` | The publishing agent's ID |
| `topic` | `str` | The topic to publish on |
| `payload` | `dict \| None` | Message body. Defaults to `{}` |

---

### `unsubscribe(agent_id, topic)`

Remove all subscriptions of `agent_id` on `topic`.

```python
bus.unsubscribe("user:abc123", "advisor.insight")
```

Called by the Gateway when a user disconnects to clean up their per-topic subscriptions.

| Parameter | Type | Description |
|---|---|---|
| `agent_id` | `str` | The agent to unsubscribe |
| `topic` | `str` | The topic to unsubscribe from |

---

### `topics() → list[str]`

Return all topics with at least one active subscriber.

```python
active_topics = bus.topics()
```

**Returns:** `list[str]`

## Message Handler Signature

Handlers registered via `subscribe()` receive the full message as a dict:

```python
async def my_handler(message: dict) -> None:
    sender  = message["sender"]
    topic   = message["topic"]
    payload = message["payload"]
    ts      = message["timestamp"]
```

## Design Notes

**Decoupling.** Neither the publisher nor the subscriber holds a reference to the other. They only share a topic name string. New subscribers can be added without modifying the publisher.

**Delivery order.** Messages are delivered in subscription order within a topic. Delivery across different topics is not ordered.

**Error isolation.** If a handler raises, the error is caught and printed. Other subscribers on the same topic continue to receive the message.

**WorldState vs MessageBus.** Use WorldState for persistent, readable state that agents and the Gateway need to query at any time. Use the MessageBus for transient notifications and typed events where the publisher does not need the consumer to store the result.
