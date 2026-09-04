# Introduction

## What is MIVAIS?

MIVAIS is a Python library that provides the infrastructure layer for mixed-initiative visual analytics systems. It handles the concerns that are common to all such systems — shared state, access control, audit logging, real-time WebSocket delivery, and session recording — so that application code can focus entirely on domain logic.

It is intentionally narrow. MIVAIS does not implement ranking algorithms, machine learning models, or data visualisations. It provides the substrate on which those components operate.

## The Problem

When you start building a mixed-initiative system without explicit infrastructure, the same problems appear every time:

- Access control is ad-hoc — permissions are checked (or not) inside individual handlers.
- State changes are invisible — there is no record of who changed what, or when.
- Agents are tightly coupled — adding a new agent requires modifying existing ones.
- The frontend is hard to keep in sync — every state change requires manual broadcast logic.
- Roles are inconsistent — a human user and a software agent follow different code paths.

These problems compound. A system that starts small becomes difficult to extend once business logic and infrastructure concerns are tangled together.

## How MIVAIS Solves It

MIVAIS separates infrastructure from domain logic through six composable components:

| Component | Responsibility |
|---|---|
| `WorldState` | The shared blackboard. All state lives here. Every write is permission-checked and audit-logged. |
| `MessageBus` | Typed publish/subscribe. Used for transient events that should not be stored as state. |
| `AgentRegistry` | Registers agents and their declared capabilities. The PermissionGuard reads from it. |
| `PermissionGuard` | Enforces write boundaries on every `WorldState.write()` call. |
| `AuditLog` | Immutable record of every write attempt and bus message. Never cleared. |
| `Gateway` | WebSocket bridge. Registers users as agents, routes messages, broadcasts state. |
| `SessionRecorder` | Writes every event to a JSONL file for replay and analysis. |

Agents and users interact only through `WorldState` and `MessageBus`. They never hold references to each other. This decoupling is enforced structurally, not by convention.

## Design Goals

**Every participant follows the same rules.** A human user who submits data through the frontend is registered as an agent in `AgentRegistry` with declared `can_write` permissions. Their write goes through `PermissionGuard` identically to a write from an autonomous agent. The `AuditLog` records both with equal specificity.

**Permissions are visible.** Agent capabilities are declared in a configuration file. The permission topology of a running system — which agents can read and write which keys, which topics connect them — can be inspected at runtime via `AgentRegistry.summary()`.

**Nothing is silent.** A denied write produces an audit entry. A bus message produces an audit entry. An accepted write produces an audit entry and notifies all registered watchers. There is no action in the system that leaves no trace.

**Adding a component does not break others.** Agents communicate through WorldState and the bus, not through direct references. A new agent that watches `result_key` and publishes on `insights.ready` can be added without modifying the agent that writes `result_key`.

## What MIVAIS Does Not Provide

- Frontend code. The client-side implementation is the application's responsibility.
- Domain algorithms. Ranking, scoring, clustering, and similar computations are implemented in your agents.
- A database layer. WorldState is in-memory. Persistence beyond the session is outside MIVAIS's scope.
- A process model. MIVAIS runs in a single Python process using asyncio. Horizontal scaling requires additional infrastructure.

## Next Steps

- [Core Concepts](/guide/concepts) — understand the five key patterns before writing any code.
- [Building a System](/guide/building) — a complete walkthrough of a MIVAIS application from first line to running server.
- [Configuration](/guide/configuration) — the full reference for `agents_config.yaml`.
