---
layout: home

hero:
  name: "MIVAIS"
  text: "Infrastructure for Mixed-Initiative Visual Analytics"
  tagline: Six composable components that handle governance, access control, audit logging, and real-time delivery — so you can focus on your domain logic.
  actions:
    - theme: brand
      text: Read the Guide
      link: /guide/introduction
    - theme: alt
      text: API Reference
      link: /api/overview

features:
  - title: Shared State with Access Control
    details: WorldState is the single shared blackboard for all participants. Every write is permission-checked by PermissionGuard before it is applied — with full audit logging whether the write is accepted or rejected.

  - title: Declarative Permissions
    details: Capabilities are declared in a configuration file, not scattered across agent code. Adding a new agent or user role means editing JSON, not Python.

  - title: Reactive Agents
    details: Agents register async watchers on WorldState keys. When state changes, the relevant agents fire immediately — no polling, no tight coupling between components.

  - title: Typed Message Bus
    details: MessageBus provides a publish/subscribe channel for events that should not be stored in state. Agents and users never hold references to each other — only topic names.

  - title: Extensible WebSocket Gateway
    details: The Gateway registers every connected user as an agent with role-based permissions. Extend it with one method override to add domain-specific frontend actions.

  - title: Complete Provenance
    details: AuditLog records every write attempt and every bus message, permanently. SessionRecorder writes a timestamped JSONL file per session for post-hoc analysis and replay.
---

## At a Glance

A MIVAIS application is wired together in six lines:

```python
from mivais import AuditLog, AgentRegistry, PermissionGuard, WorldState, MessageBus, Gateway

audit    = AuditLog()
registry = AgentRegistry()
guard    = PermissionGuard(registry)
state    = WorldState(audit, guard)
bus      = MessageBus(audit)
gateway  = Gateway(state, audit, registry, bus, user_configs=config["users"])
```

Every agent, user, and action in the system operates through these six objects. Nothing bypasses them.
