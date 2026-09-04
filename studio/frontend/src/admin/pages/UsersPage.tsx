import { useEffect, useState, type FormEvent } from "react";
import { apiDelete, apiGet, apiPost, ApiError } from "../../lib/api";
import type { AdminUserRow } from "../types";

export function UsersPage() {
  const [data, setData] = useState<{ users: AdminUserRow[]; me: string } | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    const res = await apiGet<{ users: AdminUserRow[]; me: string }>("/api/admin/users");
    setData(res);
  }

  useEffect(() => {
    load();
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    try {
      const res = await apiPost<{ message?: string }>("/api/admin/users", { username, password });
      setMessage(res.message ?? null);
      setUsername("");
      setPassword("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  async function onDelete(userId: string) {
    setError(null);
    try {
      await apiDelete(`/api/admin/users/${userId}`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  if (!data) return <p className="muted">Loading…</p>;

  return (
    <div>
      <div className="page-head">
        <h1>Admin users</h1>
      </div>
      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert success">{message}</div>}

      <div className="card">
        <table className="data">
          <thead>
            <tr>
              <th>Username</th>
              <th>Created</th>
              <th>Last login</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.users.map((u) => (
              <tr key={u.id}>
                <td className="mono">
                  {u.username} {u.username === data.me && <span className="chip">you</span>}
                </td>
                <td className="small muted">{new Date(u.created_at).toLocaleString()}</td>
                <td className="small muted">{u.last_login ? new Date(u.last_login).toLocaleString() : "never"}</td>
                <td>
                  {u.username !== data.me && (
                    <button type="button" className="btn danger" onClick={() => onDelete(u.id)}>
                      Delete
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Add a user</h2>
        <form onSubmit={onCreate} className="form-card">
          <label className="field">
            Username
            <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} required />
          </label>
          <label className="field">
            Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
          </label>
          <button type="submit" className="btn primary">
            Create
          </button>
        </form>
      </div>
    </div>
  );
}
