import type { AuditEntry, ConnectedUser } from "mivais-va-client";
import type { PodiumWorldState } from "../types";
import {
  AuditLogDiagram,
  ArrowMarkerDefs,
  BusFanoutDiagram,
  GatewayBridgeDiagram,
  LLMAgentDiagram,
  PermGuardDiagram,
  ReactiveAgentDiagram,
  WritePipelineDiagram,
} from "./diagrams";
import { actorColor, timeAgo, valueDesc } from "./utils";

export interface InspectorProps {
  nodeId: string;
  worldState: Partial<PodiumWorldState>;
  auditLog: AuditEntry[];
  connectedUsers: ConnectedUser[];
  busCount: number;
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <div className="ins-step">
      <span className="ins-step-num">{n}.</span>
      <span>{children}</span>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="ins-section">
      <div className="ins-label">{label}</div>
      {children}
    </div>
  );
}

function WorldStateInspector({ worldState, auditLog }: InspectorProps) {
  const keys = Object.keys(worldState).filter((k) => k !== "dataset");
  const recent = [...auditLog].slice(-5).reverse();
  const recentKeys = new Set(recent.filter((e) => e.event_type === "state_write" || e.event_type === "write").map((e) => e.key));

  return (
    <>
      <div className="ins-title">WorldState</div>
      <div className="ins-pattern">Pattern: Blackboard Architecture (HEARSAY-II, 1980)</div>
      <div className="ins-pattern">Role: Shared memory for all agents</div>
      <div className="ins-divider" />
      <Section label={`Current State (${keys.length} keys)`}>
        {keys.length ? (
          keys.map((k) => {
            const isRecent = recentKeys.has(k);
            return (
              <div className="ins-row" key={k}>
                <span className="ins-key">• {k}</span>
                <span className={`ins-val${isRecent ? " flash-recent" : ""}`}>
                  {valueDesc((worldState as Record<string, unknown>)[k])}
                  {isRecent ? " ↑" : ""}
                </span>
              </div>
            );
          })
        ) : (
          <div style={{ color: "var(--muted)", fontSize: 10 }}>No data yet.</div>
        )}
      </Section>
      <Section label="Active Watchers">
        <div className="ins-watcher-row">
          <span className="w-name">svm_ranker</span> → watches session_nudges, dataset
        </div>
        <div className="ins-watcher-row">
          <span className="w-name">gateway</span> → watch_any() (all keys)
        </div>
      </Section>
      <Section label="How It Works">
        <WritePipelineDiagram />
        <Step n={1}>Agent calls _write(key, value)</Step>
        <Step n={2}>PermGuard.can_write(actor, key) checked</Step>
        <Step n={3}>If accepted: value stored in _data dict</Step>
        <Step n={4}>All watch() callbacks notified</Step>
        <Step n={5}>AuditLog entry created (accepted/denied)</Step>
        <Step n={6}>Gateway broadcasts state_update to all users</Step>
      </Section>
    </>
  );
}

function MessageBusInspector({ connectedUsers, busCount }: InspectorProps) {
  return (
    <>
      <div className="ins-title">MessageBus</div>
      <div className="ins-pattern">Pattern: Publisher-Subscriber (Observer)</div>
      <div className="ins-pattern">Role: Decoupled async message delivery</div>
      <div className="ins-divider" />
      <Section label="Active Subscriptions">
        <div className="ins-topic-block">
          <div className="ins-topic-name">chat.message</div>
          <div className="ins-topic-line">Publishers: nl_command, users</div>
          <div className="ins-topic-line">Subscribers: gateway</div>
        </div>
        <div className="ins-topic-block">
          <div className="ins-topic-name">nl_command.request</div>
          <div className="ins-topic-line">Publishers: users (analyst, curator)</div>
          <div className="ins-topic-line">Subscribers: nl_command</div>
        </div>
        <div className="ins-topic-block">
          <div className="ins-topic-name">nl_command.response</div>
          <div className="ins-topic-line">Publishers: nl_command</div>
          <div className="ins-topic-line">Subscribers: users (via per-user sub)</div>
        </div>
      </Section>
      <Section label="Stats">
        <div className="ins-count-row">
          <span className="ins-count-chip">
            Total messages: <b>{busCount}</b>
          </span>
          <span className="ins-count-chip">
            Subscribers: <b>{3 + connectedUsers.length}</b>
          </span>
        </div>
      </Section>
      <Section label="How It Works">
        <BusFanoutDiagram />
        <Step n={1}>Agent calls _publish(topic, payload)</Step>
        <Step n={2}>BusMessage created {"{id, topic, sender, payload, ts}"}</Step>
        <Step n={3}>asyncio.Task created for each subscriber callback</Step>
        <Step n={4}>Tasks run independently — failure isolated</Step>
        <Step n={5}>AuditLog entry created for the message</Step>
      </Section>
    </>
  );
}

function GatewayInspector({ connectedUsers }: InspectorProps) {
  return (
    <>
      <div className="ins-title">Gateway</div>
      <div className="ins-pattern">Role: WebSocket bridge between clients and infrastructure</div>
      <div className="ins-pattern">Pattern: Mediator</div>
      <div className="ins-divider" />
      <Section label={`Connected Users (${connectedUsers.length})`}>
        {connectedUsers.length ? (
          connectedUsers.map((u) => {
            const isAnalyst = u.role === "analyst" || u.role === "curator";
            return (
              <div className="ins-user-row" key={u.session_id}>
                <div className="ins-user-icon">
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" style={{ color: "var(--cyan)" }}>
                    <circle cx="8" cy="5" r="3" />
                    <path d="M2 14c0-3.3 2.7-6 6-6s6 2.7 6 6" />
                  </svg>
                </div>
                <div className="ins-user-info">
                  <div className="ins-user-id">
                    user:{u.session_id.slice(0, 8)} <span className="ins-user-online">● live</span>
                  </div>
                  <div className="ins-user-role">Role: {u.role}</div>
                  <div className="ins-user-role" style={{ color: "var(--muted)" }}>
                    can_write: {isAnalyst ? "session_nudges, display_order" : "(read-only)"}
                  </div>
                </div>
              </div>
            );
          })
        ) : (
          <div style={{ color: "var(--muted)", fontSize: 10 }}>No users connected.</div>
        )}
      </Section>
      <Section label="Infrastructure Bridges">
        <div className="ins-watcher-row">• Watches ALL WorldState keys → pushes state_update</div>
        <div className="ins-watcher-row">• Subscribes to chat.message → routes (broadcast or private)</div>
        <div className="ins-watcher-row">• Subscribes to nl_command.response → delivers to user</div>
        <div className="ins-watcher-row">• Handles publish_bus action from WebSocket clients</div>
      </Section>
      <Section label="How It Works">
        <GatewayBridgeDiagram connectedUsers={connectedUsers} />
        <Step n={1}>User connects via WebSocket → registered in AgentRegistry</Step>
        <Step n={2}>On user message: validates role permissions → routes to action</Step>
        <Step n={3}>On WS write: Gateway._write() bypasses PermGuard (system actor)</Step>
        <Step n={4}>On bus message delivery: routes to target WebSocket(s)</Step>
      </Section>
    </>
  );
}

function AuditLogInspector({ auditLog }: InspectorProps) {
  const counts = { state_write: 0, bus_message: 0, cursor_move: 0, user_input: 0 } as Record<string, number>;
  auditLog.forEach((e) => {
    const t = e.event_type === "write" ? "state_write" : e.event_type ?? "";
    if (counts[t] !== undefined) counts[t]++;
  });
  const recent = [...auditLog].slice(-10).reverse();

  return (
    <>
      <div className="ins-title">AuditLog</div>
      <div className="ins-pattern">Role: Immutable provenance record</div>
      <div className="ins-pattern">Pattern: Event Sourcing / Append-Only Log</div>
      <div className="ins-divider" />
      <Section label={`Total Entries: ${auditLog.length}`}>
        <div className="ins-count-row">
          <span className="ins-count-chip">
            state_write <b>{counts.state_write}</b>
          </span>
          <span className="ins-count-chip">
            bus_message <b>{counts.bus_message}</b>
          </span>
          <span className="ins-count-chip">
            cursor_move <b>{counts.cursor_move}</b>
          </span>
          <span className="ins-count-chip">
            user_input <b>{counts.user_input}</b>
          </span>
        </div>
      </Section>
      <Section label="Recent Entries (last 10)">
        {recent.length ? (
          recent.map((e) => {
            const accepted = e.accepted !== false;
            const evType = e.event_type ?? "";
            const label = evType === "state_write" || evType === "write" ? (accepted ? "WRITE" : "DENY") : evType.toUpperCase();
            return (
              <div className="ins-recent-entry" key={e.id}>
                <span className="ins-recent-actor" style={{ color: actorColor(e.actor) }}>
                  {e.actor}
                </span>
                {e.key && (
                  <>
                    {" → "}
                    <b style={{ color: "var(--text)" }}>{e.key}</b>
                  </>
                )}{" "}
                <span style={{ color: accepted ? "var(--green)" : "var(--red)" }}>{label}</span>{" "}
                <span style={{ color: "var(--muted)" }}>{timeAgo(e.timestamp)}</span>
              </div>
            );
          })
        ) : (
          <div style={{ color: "var(--muted)", fontSize: 10 }}>No entries yet.</div>
        )}
      </Section>
      <Section label="How It Works">
        <AuditLogDiagram />
      </Section>
      <Section label="Session Recording">
        <div className="ins-watcher-row">• All entries written to JSONL file on disk</div>
        <div className="ins-watcher-row">• Supports full session replay</div>
        <div className="ins-watcher-row">• Used for: reproducibility, debugging, evaluation</div>
      </Section>
    </>
  );
}

const AGENT_DEFS = [
  { id: "svm_ranker", can_write: ["ranked_items", "weights", "svm_status", "display_order", "user_preference_ranking"], can_read: ["dataset", "numeric_cols", "session_nudges", "weights", "ranked_items"] },
  { id: "nl_command", can_write: ["display_order", "session_nudges"], can_read: ["dataset", "numeric_cols", "weights", "ranked_items", "session_nudges"] },
  { id: "user (analyst)", can_write: ["session_nudges", "display_order"], can_read: ["*"] },
  { id: "user (observer)", can_write: [] as string[], can_read: ["*"] },
];

function AgentRegistryInspector({ connectedUsers }: InspectorProps) {
  return (
    <>
      <div className="ins-title">PermGuard + Registry</div>
      <div className="ins-pattern">Role: Capability-based access control</div>
      <div className="ins-pattern">Pattern: Role-Based Access Control (RBAC)</div>
      <div className="ins-divider" />
      <Section label={`Registered Agents (${AGENT_DEFS.length - 2 + connectedUsers.length})`}>
        {AGENT_DEFS.map((a) => (
          <div className="ins-sub-block" key={a.id}>
            <div className="ins-sub-title">{a.id}</div>
            <div className="ins-perm-can">
              can_write: {a.can_write.length ? a.can_write.join(", ") : <span style={{ color: "var(--muted)" }}>(none)</span>}
            </div>
            <div className="ins-perm-no">can_read: {a.can_read.join(", ")}</div>
          </div>
        ))}
      </Section>
      <Section label="How It Works">
        <PermGuardDiagram />
        <Step n={1}>Every WorldState.write(actor, key, value) call</Step>
        <Step n={2}>PermGuard.can_write(actor, key) is called</Step>
        <Step n={3}>AgentRegistry.get(actor).can_write list checked</Step>
        <Step n={4}>Returns True (proceed) or False (deny)</Step>
        <Step n={5}>AuditLog records result (accepted/denied)</Step>
      </Section>
    </>
  );
}

function SvmRankerInspector({ auditLog }: InspectorProps) {
  const recent = [...auditLog].slice(-20).reverse().find((e) => e.actor === "svm_ranker");
  return (
    <>
      <div className="ins-title">SVMRankingAgent</div>
      <div className="ins-pattern">Strategy: Reactive (watch + bus subscribe)</div>
      <div className="ins-pattern">Trigger: session_nudges/dataset changes, compute_weights/rank_all messages</div>
      <div className="ins-divider" />
      <Section label="Description">
        <div style={{ fontSize: 10, color: "var(--muted)", lineHeight: 1.7 }}>
          Implements the ranking core of PODIUM. When the analyst clicks Compute Weights or Rank All, the request is sent as a message
          on the MessageBus; the SVM Ranker receives it, fits a Support Vector Machine to learn implicit weights, then applies a Simple
          Additive Weighting model to re-rank all items.
        </div>
      </Section>
      <Section label="Observation Strategy">
        <div className="ins-row">
          <span>WorldState watch()</span>
          <span className="ins-val">session_nudges, dataset</span>
        </div>
        <div className="ins-row">
          <span>Bus subscribe()</span>
          <span className="ins-val">weights.compute_request, rank_all.request</span>
        </div>
        <div className="ins-row">
          <span>Pattern</span>
          <span className="ins-val">Reactive / Event-driven</span>
        </div>
      </Section>
      <Section label="Permissions">
        <div className="ins-sub-block">
          <div className="ins-perm-can">can_write: ranked_items, weights, svm_status, display_order, user_preference_ranking</div>
          <div className="ins-perm-no">can_read: dataset, numeric_cols, session_nudges, weights, ranked_items</div>
        </div>
      </Section>
      <Section label="Current Status">
        <div style={{ fontSize: 10, color: "var(--muted)" }}>
          {recent ? (
            <>
              Last action: wrote <b style={{ color: "var(--text)" }}>{recent.key ?? "?"}</b> {timeAgo(recent.timestamp)}
            </>
          ) : (
            "No recent activity."
          )}
        </div>
      </Section>
      <Section label="How It Works">
        <ReactiveAgentDiagram agentId="svm_ranker" />
        <Step n={1}>Analyst clicks Compute Weights / Rank All in the UI</Step>
        <Step n={2}>Gateway publishes weights.compute_request / rank_all.request on the MessageBus</Step>
        <Step n={3}>SVM Ranker's bus subscription delivers the message to on_message()</Step>
        <Step n={4}>Reads dataset and current weights from WorldState</Step>
        <Step n={5}>Fits SVM on (item_pair, preference) training data, applies SAW to score all items</Step>
        <Step n={6}>Writes ranked_items, weights, display_order to WorldState</Step>
      </Section>
    </>
  );
}


function UserInspector({ nodeId, connectedUsers }: InspectorProps) {
  const shortId = nodeId.replace("user:", "");
  const user = connectedUsers.find((u) => u.session_id === shortId);
  const role = user?.role ?? "observer";
  const isAnalyst = role === "analyst" || role === "curator";

  return (
    <>
      <div className="ins-title">User: {nodeId}</div>
      <div className="ins-pattern">Role: {role}</div>
      <div className="ins-divider" />
      <Section label="Connection Info">
        <div className="ins-row">
          <span>Session ID</span>
          <span className="ins-val">{shortId.slice(0, 8)}</span>
        </div>
        <div className="ins-row">
          <span>Role</span>
          <span className="ins-val">{role}</span>
        </div>
        <div className="ins-row">
          <span>Status</span>
          <span className="ins-val ins-user-online">● live</span>
        </div>
      </Section>
      <Section label="Permissions">
        <div className="ins-sub-block">
          {isAnalyst ? (
            <div className="ins-perm-can">can_write: session_nudges, display_order</div>
          ) : (
            <div className="ins-perm-no">can_write: (none — read-only)</div>
          )}
          <div className="ins-perm-no">can_read: all WorldState keys</div>
        </div>
      </Section>
      <Section label="Bus Access">
        <div className="ins-row">
          <span>subscribe</span>
          <span className="ins-val">nl_command.response (per-user sub)</span>
        </div>
        <div className="ins-row">
          <span>publish</span>
          <span className="ins-val">
            {isAnalyst ? "nl_command.request, chat.message, weights.compute_request, rank_all.request" : "(none)"}
          </span>
        </div>
      </Section>
      <Section label="As an Agent">
        <div className="ins-watcher-row">• Registered in AgentRegistry as "{nodeId}"</div>
        <div className="ins-watcher-row">• Same permission model as software agents</div>
        <div className="ins-watcher-row">• Actions via WebSocket → Gateway → WorldState</div>
        <div className="ins-watcher-row">• Gateway uses system actor for direct WS writes</div>
      </Section>
    </>
  );
}

export function InspectorContent(props: InspectorProps) {
  const { nodeId } = props;
  let body: React.ReactNode;
  switch (nodeId) {
    case "worldstate":
      body = <WorldStateInspector {...props} />;
      break;
    case "messagebus":
      body = <MessageBusInspector {...props} />;
      break;
    case "gateway":
      body = <GatewayInspector {...props} />;
      break;
    case "auditlog":
      body = <AuditLogInspector {...props} />;
      break;
    case "agentregistry":
      body = <AgentRegistryInspector {...props} />;
      break;
    case "svm_ranker":
      body = <SvmRankerInspector {...props} />;
      break;
    default:
      body = nodeId.startsWith("user:") ? (
        <UserInspector {...props} />
      ) : (
        <>
          <div className="ins-title">{nodeId}</div>
          <p style={{ color: "var(--muted)", marginTop: 8 }}>No details available.</p>
        </>
      );
  }
  return (
    <>
      <ArrowMarkerDefs />
      {body}
    </>
  );
}
