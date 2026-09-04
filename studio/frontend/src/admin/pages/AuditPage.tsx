import { useEffect, useState } from "react";
import { apiGet } from "../../lib/api";
import type { AuditEntry } from "../types";

export function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);

  useEffect(() => {
    apiGet<{ entries: AuditEntry[] }>("/api/admin/audit").then((res) => setEntries(res.entries));
  }, []);

  if (!entries) return <p className="muted">Loading…</p>;

  return (
    <div>
      <div className="page-head">
        <h1>Audit log</h1>
      </div>
      <div className="card">
        <table className="data compact">
          <thead>
            <tr>
              <th>When</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Target</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td className="small muted">{new Date(e.ts).toLocaleString()}</td>
                <td className="mono small">{e.actor_username ?? "system"}</td>
                <td className="mono small">{e.action}</td>
                <td className="mono small">
                  {e.target_type}
                  {e.target_id ? `:${e.target_id.slice(-8)}` : ""}
                </td>
              </tr>
            ))}
            {entries.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  No audit entries yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
