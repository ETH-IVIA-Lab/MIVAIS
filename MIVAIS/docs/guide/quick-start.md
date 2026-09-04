# Quick Start

This guide walks through setting up a minimal MIVAIS application: a FastAPI backend with one autonomous agent and a WebSocket endpoint for browser clients.

## Prerequisites

- Python 3.11+
- `fastapi` and `uvicorn` installed (`pip install fastapi uvicorn`)

## Project Layout

```
my_app/
├── main.py
├── agents_config.yaml
└── agents/
    └── my_agent.py
```

Copy the `mivais/` directory into your project root, or add it as a package.

## Step 1 — Define Agent Capabilities

Create `agents_config.yaml`. This file declares all user roles and agent capabilities. The infrastructure reads it at startup — no permissions are hardcoded in Python.

```yaml
users:
  analyst:
    description: Full read/write access
    can_read: []
    can_write:
    - user_input
    bus_publish_topics:
    - chat.message
    bus_subscribe_topics:
    - chat.message
    - advisor.insight
  observer:
    description: Read-only access
    can_read: []
    can_write: []
    bus_publish_topics: []
    bus_subscribe_topics:
    - chat.message
    - advisor.insight
agents:
- agent_id: my_agent
  role: processor
  description: Reacts to user_input and writes a result
  enabled: true
  class: agents.my_agent.MyAgent
  trigger: watch
  can_read:
  - user_input
  can_write:
  - result
  bus_publish_topics:
  - advisor.insight
  bus_subscribe_topics: []
  params: {}
```

## Step 2 — Implement an Agent

```python
# agents/my_agent.py
import asyncio
from typing import Any
from mivais import BaseAgent

class MyAgent(BaseAgent):
    async def run(self) -> None:
        self._ws.watch("user_input", self._on_input)
        # Keep the coroutine alive
        await asyncio.get_event_loop().create_future()

    async def _on_input(self, key: str, value: Any) -> None:
        # Read, compute, write
        result = {"processed": value, "length": len(str(value))}
        self._write("result", result)
        await self._publish("advisor.insight", {"summary": f"Processed input: {value}"})
```

## Step 3 — Wire Up the Application

```python
# main.py
import asyncio
import importlib
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from mivais import (
    AuditLog, AgentRegistry, AgentCapabilities,
    PermissionGuard, WorldState, MessageBus, Gateway,
)

CONFIG_PATH = Path("agents_config.yaml")
tasks: list[asyncio.Task] = []


def load_config():
    return json.loads(CONFIG_PATH.read_text())


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()

    # Build infrastructure singletons
    audit    = AuditLog()
    registry = AgentRegistry()
    guard    = PermissionGuard(registry)
    state    = WorldState(audit, guard)
    bus      = MessageBus(audit)
    gateway  = Gateway(state, audit, registry, bus, user_configs=config["users"])

    # Register and start each enabled agent
    for agent_cfg in config["agents"]:
        if not agent_cfg.get("enabled", True):
            continue

        module_path, class_name = agent_cfg["class"].rsplit(".", 1)
        AgentClass = getattr(importlib.import_module(module_path), class_name)

        caps = AgentCapabilities(
            agent_id=agent_cfg["agent_id"],
            role=agent_cfg["role"],
            description=agent_cfg.get("description", ""),
            can_read=agent_cfg.get("can_read", []),
            can_write=agent_cfg.get("can_write", []),
            bus_publish_topics=agent_cfg.get("bus_publish_topics", []),
            bus_subscribe_topics=agent_cfg.get("bus_subscribe_topics", []),
            trigger=agent_cfg.get("trigger", "watch"),
            params=agent_cfg.get("params", {}),
        )
        agent = AgentClass(caps.agent_id, state, bus, caps.params)
        registry.register(caps, agent)
        tasks.append(asyncio.create_task(agent.run()))

    app.state.gateway = gateway
    app.state.state   = state
    app.state.audit   = audit
    app.state.registry = registry

    yield

    for t in tasks:
        t.cancel()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    role: str = Query(default="analyst"),
):
    gateway: Gateway = app.state.gateway
    await gateway.connect(session_id, websocket, role=role)
    try:
        while True:
            raw = await websocket.receive_text()
            await gateway.receive_and_apply(session_id, raw)
    except WebSocketDisconnect:
        await gateway.disconnect(session_id)


@app.get("/audit")
def get_audit():
    return app.state.audit.get_all()


@app.get("/agents")
def get_agents():
    return app.state.registry.summary()
```

## Step 4 — Run

```bash
uvicorn main:app --reload
```

Connect a WebSocket client to `ws://localhost:8000/ws/my-session?role=analyst`.

## What Happens at Runtime

1. A client connects → Gateway registers them as `user:my-session` with `analyst` permissions.
2. The client sends `{"action": "set_value", "key": "user_input", "value": "hello"}`.
3. Since `set_value` is not a built-in Gateway action, it reaches `_handle_action()` — which you have not overridden yet, so nothing happens.
4. To handle it, subclass `Gateway` and override `_handle_action`:

```python
from mivais import Gateway

class AppGateway(Gateway):
    async def _handle_action(self, agent_id, session_id, data):
        if data.get("action") == "set_value":
            self._ws.write(agent_id, "user_input", data.get("value"))
```

5. `WorldState.write()` checks permissions → `analyst` has `user_input` in `can_write` → accepted.
6. `AuditLog` records the write.
7. `WorldState` notifies `MyAgent`'s watcher → agent computes, writes `result`.
8. Gateway's `watch_any` fires → broadcasts full state update to all connected clients.

See [Architecture](/guide/architecture) for a deeper look at this data flow.
