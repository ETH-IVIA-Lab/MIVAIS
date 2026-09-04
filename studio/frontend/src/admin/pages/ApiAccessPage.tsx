import { useEffect, useState } from "react";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { apiDelete, apiGet, apiPost, ApiError } from "../../lib/api";

interface ApiKeyRow {
  id: string;
  name: string;
  prefix: string;
  created_by: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

const ENDPOINTS: { path: string; what: string }[] = [
  { path: "GET /api/v1/studies", what: "List registered studies" },
  { path: "GET /api/v1/studies/{slug}", what: "Study detail incl. blocks, roles, metrics config" },
  { path: "GET /api/v1/studies/{slug}/sessions", what: "Sessions of a study (paginated, ?status= filter)" },
  { path: "GET /api/v1/studies/{slug}/metrics", what: "Behavioral metrics: aggregates + per participant" },
  { path: "GET /api/v1/sessions/{id}", what: "Session detail incl. participants and VA systems" },
  { path: "GET /api/v1/sessions/{id}/events", what: "Full event timeline (paginated; ?after_t_ms= to poll a running session)" },
  { path: "GET /api/v1/sessions/{id}/answers", what: "Per-participant task runs: answers, scores, timings, steps" },
  { path: "GET /api/v1/sessions/{id}/metrics", what: "Behavioral metrics for this session" },
  { path: "GET /api/v1/sessions/{id}/annotations", what: "Markers (incl. transcript quotes), notes, tags" },
  { path: "GET /api/v1/sessions/{id}/transcript", what: "Speech transcript segments (?run= per POV)" },
];

export function ApiAccessPage() {
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [name, setName] = useState("");
  const [minted, setMinted] = useState<{ token: string; name: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const res = await apiGet<{ keys: ApiKeyRow[] }>("/api/admin/apikeys");
    setKeys(res.keys);
  }

  useEffect(() => {
    load();
  }, []);

  async function onMint() {
    setError(null);
    try {
      const res = await apiPost<{ key: ApiKeyRow; token: string }>("/api/admin/apikeys", { name });
      setMinted({ token: res.token, name: res.key.name });
      setName("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  const [confirmKey, setConfirmKey] = useState<ApiKeyRow | null>(null);

  async function onRevoke(k: ApiKeyRow) {
    setConfirmKey(null);
    setError(null);
    try {
      await apiDelete(`/api/admin/apikeys/${k.id}`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  return (
    <div>
      <ConfirmDialog
        open={confirmKey !== null}
        title="Revoke this API key?"
        body={
          <>
            <strong>{confirmKey?.name}</strong> (<code>{confirmKey?.prefix}…</code>) stops working
            immediately — any tool using it will start failing.
          </>
        }
        confirmLabel="Revoke key"
        onConfirm={() => confirmKey && onRevoke(confirmKey)}
        onCancel={() => setConfirmKey(null)}
      />

      <div className="page-head">
        <div>
          <h1>API access</h1>
          <p className="muted small">
            Read-only programmatic access for external tools (analysis pipelines, dashboards, notebooks). Mint a
            key, send it as <code>Authorization: Bearer &lt;token&gt;</code>. Interactive schema at{" "}
            <a href="/docs" target="_blank" rel="noopener noreferrer">
              /docs
            </a>
            .
          </p>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {minted && (
        <div className="alert success" style={{ wordBreak: "break-all" }}>
          Key <b>{minted.name}</b> minted — copy the token now, it is <b>shown only once</b>:
          <div className="mono" style={{ marginTop: 6, userSelect: "all" }}>
            {minted.token}
          </div>
        </div>
      )}

      <div className="card">
        <h2>Keys</h2>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
          <input
            placeholder="Key name (e.g. R pipeline)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ maxWidth: 280 }}
          />
          <button type="button" className="btn primary" onClick={onMint}>
            + Mint key
          </button>
        </div>
        <table className="data">
          <thead>
            <tr>
              <th>Name</th>
              <th>Token prefix</th>
              <th>Created</th>
              <th>Last used</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id}>
                <td>{k.name}</td>
                <td className="mono small">{k.prefix}…</td>
                <td className="small muted">
                  {new Date(k.created_at).toLocaleString()} · {k.created_by}
                </td>
                <td className="small muted">{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "never"}</td>
                <td>{k.revoked ? <span className="chip error">revoked</span> : <span className="chip ok">active</span>}</td>
                <td>
                  {!k.revoked && (
                    <button type="button" className="btn ghost" onClick={() => setConfirmKey(k)}>
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {keys.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  No keys yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Endpoints</h2>
        <p className="muted small">
          All read-only. Example:{" "}
          <code>curl -H &quot;Authorization: Bearer mvs_…&quot; https://&lt;host&gt;/api/v1/studies</code>
        </p>
        <table className="data" style={{ marginTop: 10 }}>
          <thead>
            <tr>
              <th>Endpoint</th>
              <th>Returns</th>
            </tr>
          </thead>
          <tbody>
            {ENDPOINTS.map((e) => (
              <tr key={e.path}>
                <td className="mono small">{e.path}</td>
                <td className="small">{e.what}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
