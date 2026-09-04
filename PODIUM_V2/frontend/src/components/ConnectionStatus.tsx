import type { ConnectionStatus as Status } from "mivais-va-client";

export function ConnectionStatus({ status, role }: { status: Status; role?: string }) {
  const label =
    status === "connected" ? `Connected${role ? ` · ${role}` : ""}` : status === "reconnecting" ? "Reconnecting…" : "Connecting…";
  return (
    <div className="conn">
      <div className={`conn-dot${status === "connected" ? " on" : ""}`} />
      <span>{label}</span>
    </div>
  );
}
