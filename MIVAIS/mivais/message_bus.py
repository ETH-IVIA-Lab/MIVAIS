"""
MessageBus — Typed async message passing between agents.

Agents publish messages by topic. Agents subscribe by topic.
No agent holds a reference to another agent — the bus is the only bridge.

"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Iterable

from .audit_log import AuditLog

if TYPE_CHECKING:
    from .session_recorder import SessionRecorder

MessageHandler = Callable[[dict], Awaitable[None]]


class BusMessage:
    """A single typed message on the bus."""
    __slots__ = ("id", "timestamp", "sender", "topic", "payload")

    def __init__(self, sender: str, topic: str, payload: dict[str, Any]) -> None:
        self.id = str(uuid.uuid4())
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.sender = sender
        self.topic = topic
        self.payload = payload

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "sender": self.sender,
            "topic": self.topic,
            "payload": self.payload,
        }


class MessageBus:
    """
    Typed async message bus.

    Usage:
      # Agent A subscribes to a topic
      bus.subscribe("advisor_agent", "ranking.ready", my_handler)

      # Agent B publishes (e.g. after completing a computation)
      await bus.publish("ranker_agent", "ranking.ready", {"items": [...]})

    The bus logs every published message and async-delivers to all subscribers.
    No agent knows which other agents are subscribed to the same topic.
    """

    def __init__(
        self,
        audit_log: AuditLog,
        recorder: "SessionRecorder | None" = None,
        record_exclude_topics: Iterable[str] = (),
    ) -> None:
        """
        Args:
            audit_log:  Every published message is logged here.
            recorder:   Optional SessionRecorder; when set, published messages
                        are also written to the session recording as
                        ``bus_message`` events so they appear in replay.
            record_exclude_topics:  Topics recorded to the AuditLog but NOT to
                        the session recording — for high-volume telemetry
                        topics that would bloat the recording file.
        """
        # topic → list of (subscriber_agent_id, handler)
        self._subscriptions: dict[str, list[tuple[str, MessageHandler]]] = {}
        self._audit = audit_log
        self._recorder = recorder
        self._record_exclude = frozenset(record_exclude_topics)

    def subscribe(
        self,
        agent_id: str,
        topic: str,
        handler: MessageHandler,
    ) -> None:
        """
        Register agent_id as a subscriber to messages on `topic`.
        `handler` is an async callable that receives the message dict.
        """
        self._subscriptions.setdefault(topic, []).append((agent_id, handler))

    async def publish(
        self,
        sender: str,
        topic: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """
        Publish a typed message on `topic`.

        Steps:
          1. Create BusMessage
          2. Log to AuditLog (event_type="bus_message")
          3. Async-deliver to all subscribers of `topic`
        """
        msg = BusMessage(sender=sender, topic=topic, payload=payload or {})
        self._audit.record_bus_message(
            sender=sender,
            topic=topic,
            payload=payload,
        )
        if self._recorder is not None and topic not in self._record_exclude:
            self._recorder.record("bus_message", {
                "sender": sender,
                "topic": topic,
                "payload": payload or {},
            })
        subscribers = list(self._subscriptions.get(topic, []))
        for _subscriber_id, handler in subscribers:
            asyncio.create_task(_safe_deliver(handler, msg.to_dict()))

    def unsubscribe(self, agent_id: str, topic: str) -> None:
        """Remove all subscriptions of agent_id on topic."""
        if topic in self._subscriptions:
            self._subscriptions[topic] = [
                (aid, h) for aid, h in self._subscriptions[topic] if aid != agent_id
            ]

    def topics(self) -> list[str]:
        """Return all topics with at least one subscriber."""
        return list(self._subscriptions.keys())


async def _safe_deliver(handler: MessageHandler, message: dict) -> None:
    """Deliver a message without crashing the bus if the handler raises."""
    try:
        await handler(message)
    except Exception as exc:
        print(f"[message_bus] delivery error: {exc}")
