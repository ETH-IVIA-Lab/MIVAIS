import { hashUserColor } from "mivais-va-client";
import type { ConnectedUser } from "mivais-va-client";

export function ConnectedUsersBar({ users, ownSessionId }: { users: ConnectedUser[]; ownSessionId: string }) {
  const others = users.filter((u) => u.session_id !== ownSessionId);
  if (!others.length) return <div className="users-bar" />;
  return (
    <div className="users-bar">
      {others.map((u) => {
        const color = hashUserColor(u.session_id);
        return (
          <div
            key={u.session_id}
            className="user-pill"
            style={{ color, borderColor: color, background: `${color}18` }}
            title={u.session_id}
          >
            <div className="user-pill-dot" />
            {u.session_id.slice(0, 4)} <span style={{ opacity: 0.65 }}>{u.role}</span>
          </div>
        );
      })}
    </div>
  );
}
