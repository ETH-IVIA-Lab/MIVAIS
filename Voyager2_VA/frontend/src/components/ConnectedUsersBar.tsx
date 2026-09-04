import { hashUserColor } from "mivais-va-client";
import type { ConnectedUser } from "mivais-va-client";

const PALETTE = ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316"];

export function ConnectedUsersBar({ users, ownSessionId }: { users: ConnectedUser[]; ownSessionId: string }) {
  const others = users.filter((u) => u.session_id !== ownSessionId);
  if (!others.length) return <div className="users-bar" />;
  return (
    <div className="users-bar">
      {others.map((u) => {
        const color = hashUserColor(u.session_id, PALETTE);
        return (
          <div
            key={u.session_id}
            className="user-pill-small"
            style={{ color, borderColor: color, background: `${color}18` }}
          >
            <div className="user-pill-dot" />
            {u.session_id.slice(0, 4)} <span style={{ opacity: 0.6 }}>{u.role || ""}</span>
          </div>
        );
      })}
    </div>
  );
}

export { PALETTE as VOYAGER_USER_PALETTE };
