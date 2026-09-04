import type { AuditEntry, ConnectedUser } from "mivais-va-client";
import type { PodiumWorldState } from "../types";
import { InspectorContent } from "./inspectors";

export function InspectorPane({
  active,
  selectedNodeId,
  onBack,
  worldState,
  auditLog,
  connectedUsers,
  busCount,
}: {
  active: boolean;
  selectedNodeId: string | null;
  onBack: () => void;
  worldState: Partial<PodiumWorldState>;
  auditLog: AuditEntry[];
  connectedUsers: ConnectedUser[];
  busCount: number;
}) {
  return (
    <div id="inspector-pane" style={{ display: active ? "flex" : "none" }}>
      <div id="inspector-back" onClick={onBack}>
        ← Back to Events
      </div>
      <div id="inspector-body">
        {selectedNodeId ? (
          <InspectorContent nodeId={selectedNodeId} worldState={worldState} auditLog={auditLog} connectedUsers={connectedUsers} busCount={busCount} />
        ) : (
          <p style={{ color: "var(--muted)", padding: "8px 0" }}>Click any node to inspect it.</p>
        )}
      </div>
    </div>
  );
}
