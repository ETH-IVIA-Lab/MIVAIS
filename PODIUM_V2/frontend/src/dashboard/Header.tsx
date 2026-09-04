import { useEffect, useState } from "react";
import { fetchUsers } from "mivais-va-client";
import type { UserRoleInfo } from "mivais-va-client";
import { usePodium } from "../context";
import { AgentPill } from "../components/AgentPill";
import { ConnectedUsersBar } from "../components/ConnectedUsersBar";
import { ConnectionStatus } from "../components/ConnectionStatus";
import { useAgentActivity } from "./useAgentActivity";

export function Header() {
  const { connectionStatus, role, setRole, connectedUsers, onlineAgents, sessionId } = usePodium();
  const svm = useAgentActivity("svm_ranker");
  const [roles, setRoles] = useState<UserRoleInfo[]>([]);

  useEffect(() => {
    fetchUsers().then(setRoles).catch(() => {});
  }, []);

  const svmOnline = onlineAgents.some((a) => a.id === "svm_ranker");
  const roleOptions = roles.length ? roles.map((r) => r.role) : [role];

  return (
    <header>
      <h1>PODIUM</h1>
      <div className="agents-bar">
        <AgentPill label="svm_ranker" online={svmOnline} active={svm.pillOn} variant="svm" />
      </div>
      <ConnectedUsersBar users={connectedUsers} ownSessionId={sessionId} />
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: "auto", flexShrink: 0 }}>
        <label style={{ fontSize: 10, color: "var(--muted)", fontWeight: 600, whiteSpace: "nowrap" }}>Role:</label>
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          style={{
            fontSize: 11,
            padding: "2px 6px",
            border: "1.5px solid var(--border)",
            borderRadius: 5,
            background: "var(--surface)",
            color: "var(--text)",
            cursor: "pointer",
          }}
        >
          {roleOptions.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>
      <ConnectionStatus status={connectionStatus} role={role} />
    </header>
  );
}
