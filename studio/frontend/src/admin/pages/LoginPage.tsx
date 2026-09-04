import { useState, type FormEvent } from "react";
import { apiPost, ApiError } from "../../lib/api";

export function LoginPage({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiPost("/api/admin/login", { username, password });
      onLoggedIn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-frame">
      <main className="auth-card">
        <div className="p-brand">
          <span className="mark" />
          <strong style={{ fontSize: "1.05rem" }}>MIVAIS Studio</strong>
        </div>
        <h1 style={{ marginTop: 0 }}>Sign in</h1>
        <p className="muted small" style={{ marginTop: -4 }}>
          Administrator access
        </p>
        {error && (
          <div className="alert error" style={{ marginTop: 16 }}>
            {error}
          </div>
        )}
        <form onSubmit={onSubmit} className="form-card" style={{ marginTop: 20 }}>
          <label className="field">
            Username
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              required
              autoComplete="username"
            />
          </label>
          <label className="field">
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </label>
          <button type="submit" className="btn primary" disabled={busy} style={{ width: "100%", padding: "10px 14px" }}>
            Sign in
          </button>
        </form>
      </main>
    </div>
  );
}
