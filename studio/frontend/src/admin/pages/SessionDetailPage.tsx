import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiDelete, apiGet, apiPost, ApiError } from "../../lib/api";
import type { Study } from "../../lib/types";
import type { AdminSession } from "../types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { TrashIcon } from "../components/icons";

interface EventRow {
  t_ms: number;
  source: string;
  type: string;
  task_id: string | null;
  meta: Record<string, unknown>;
}

interface PerTaskRow {
  participant_id: string;
  participant_anon: string;
  task_id: string;
  task_index: number;
  duration_ms: number | null;
  answer: unknown;
  score: number | null;
  correct: boolean | null;
  n_events_total: number;
}

interface SensorTokenRow {
  id: string;
  label: string;
  prefix: string;
  created_by: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

interface SessionDetailResponse {
  session: AdminSession;
  study: Study | null;
  recording: {
    events: EventRow[];
    n_events_total: number;
    duration_s: number | null;
    per_task: PerTaskRow[];
    participants: Array<{
      id: string;
      anon_id: string;
      role: string | null;
      status: string;
      external_id?: string | null;
    }>;
  };
  density: Array<{ t_ms: number; n: number }>;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function SessionDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<SessionDetailResponse | null>(null);
  const [tags, setTags] = useState("");
  const [noteText, setNoteText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [sensorTokens, setSensorTokens] = useState<Record<string, SensorTokenRow[]>>({});
  const [tokenLabel, setTokenLabel] = useState<Record<string, string>>({});
  const [mintedToken, setMintedToken] = useState<{ participantId: string; label: string; token: string } | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [confirmRevokeToken, setConfirmRevokeToken] = useState<{ participantId: string; token: SensorTokenRow } | null>(null);

  async function onDeleteSession() {
    setDeleting(true);
    try {
      await apiDelete(`/api/admin/sessions/${id}`);
      navigate(data?.study ? `/studies/${data.study.slug}` : "/sessions", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      setConfirmDelete(false);
    } finally {
      setDeleting(false);
    }
  }

  async function load() {
    const res = await apiGet<SessionDetailResponse>(`/api/admin/sessions/${id}`);
    setData(res);
    setTags((res.session.tags || []).join(", "));
    if (res.study?.recording?.external_sensor) {
      await loadSensorTokens(res.recording.participants.map((p) => p.id));
    }
  }

  async function loadSensorTokens(participantIds: string[]) {
    const entries = await Promise.all(
      participantIds.map(async (pid) => {
        const r = await apiGet<{ tokens: SensorTokenRow[] }>(`/api/admin/sessions/${id}/participants/${pid}/sensor-tokens`);
        return [pid, r.tokens] as const;
      }),
    );
    setSensorTokens(Object.fromEntries(entries));
  }

  async function onMintToken(participantId: string) {
    setTokenError(null);
    try {
      const res = await apiPost<{ key: SensorTokenRow; token: string }>(
        `/api/admin/sessions/${id}/participants/${participantId}/sensor-tokens`,
        { label: tokenLabel[participantId] || "" },
      );
      setMintedToken({ participantId, label: res.key.label, token: res.token });
      setTokenLabel((t) => ({ ...t, [participantId]: "" }));
      if (data) await loadSensorTokens(data.recording.participants.map((p) => p.id));
    } catch (err) {
      setTokenError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  async function onRevokeToken(participantId: string, token: SensorTokenRow) {
    setConfirmRevokeToken(null);
    setTokenError(null);
    try {
      await apiDelete(`/api/admin/sensor-tokens/${token.id}`);
      if (data) await loadSensorTokens(data.recording.participants.map((p) => p.id));
    } catch (err) {
      setTokenError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  useEffect(() => {
    load();
  }, [id]);

  async function onSaveTags(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await apiPost(`/api/admin/sessions/${id}/tags`, { tags });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  async function onAddNote(e: FormEvent) {
    e.preventDefault();
    if (!noteText.trim()) return;
    setError(null);
    try {
      await apiPost(`/api/admin/sessions/${id}/note`, { text: noteText });
      setNoteText("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  if (!data) return <p className="muted">Loading…</p>;
  const { session, study, recording } = data;

  return (
    <div>
      <ConfirmDialog
        open={confirmDelete}
        title="Delete this session?"
        body={
          <>
            Its participants, events, answers and any audio/video recordings are permanently
            removed. <strong>This cannot be undone.</strong>
          </>
        }
        confirmLabel="Delete session"
        busy={deleting}
        onConfirm={onDeleteSession}
        onCancel={() => setConfirmDelete(false)}
      />

      {error && <div className="alert error">{error}</div>}
      <div className="page-head">
        <div>
          <div className="breadcrumb">
            {study ? <Link to={`/studies/${study.slug}`}>{study.name}</Link> : "Session"} / {session.id.slice(-10)}
          </div>
          <h1>Session {session.id.slice(-10)}</h1>
          <p className="small muted">
            {session.mode} · <span className={`chip status-${session.status}`}>{session.status}</span> · started {fmtDate(session.created_at)}
          </p>
        </div>
        <div className="head-actions">
          <Link to={`/sessions/${id}/live`} className="btn ghost">
            Live
          </Link>
          <Link to={`/replay/${id}`} className="btn ghost">
            Replay
          </Link>
          <a className="btn ghost" href={`/api/admin/sessions/${id}/export.jsonl`}>
            JSONL
          </a>
          <a className="btn ghost" href={`/api/admin/sessions/${id}/export.csv`}>
            CSV
          </a>
          <button
            type="button"
            className="btn danger"
            title="Delete this session and all of its data"
            onClick={() => setConfirmDelete(true)}
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            <TrashIcon />
            Delete
          </button>
        </div>
      </div>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Duration</div>
          <div className="stat-value">{recording.duration_s ? `${Math.round(recording.duration_s)}s` : "—"}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Events</div>
          <div className="stat-value">{recording.n_events_total}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Participants</div>
          <div className="stat-value">{recording.participants.length}</div>
        </div>
      </div>

      <div className="card">
        <h2>Participants</h2>
        <table className="data">
          <thead>
            <tr>
              <th>Anon ID</th>
              <th title="Recruitment-platform id (e.g. Prolific PID) — use this to reward the participant">
                External&nbsp;ID
              </th>
              <th>Role</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {recording.participants.map((p) => (
              <tr key={p.id}>
                <td className="mono">{p.anon_id}</td>
                <td className="mono small">{p.external_id || "—"}</td>
                <td>{p.role ?? "—"}</td>
                <td>{p.status}</td>
                <td>
                  <Link to={`/participants/${p.id}`} className="btn ghost">
                    Journey
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <ConfirmDialog
          open={confirmRevokeToken !== null}
          title="Revoke this sensor ingest token?"
          body={
            <>
              <strong>{confirmRevokeToken?.token.label}</strong> (<code>{confirmRevokeToken?.token.prefix}…</code>)
              stops working immediately — the external device pushing data with it will start failing.
            </>
          }
          confirmLabel="Revoke token"
          onConfirm={() => confirmRevokeToken && onRevokeToken(confirmRevokeToken.participantId, confirmRevokeToken.token)}
          onCancel={() => setConfirmRevokeToken(null)}
        />
        <h2>External sensor ingest tokens</h2>
        {!study?.recording?.external_sensor ? (
          <p className="muted small">
            External sensor streaming is disabled for this study — set <code>recording.external_sensor: true</code> in
            the study YAML to let external devices push additional sensor data via{" "}
            <code>POST /ingest/sensor-chunk</code>.
          </p>
        ) : (
          <>
            <p className="muted small">
              For non-browser sensor sources (lab rigs, vendor SDKs) that can't use the participant's browser cookie —
              distinct from the built-in BLE heart-rate pairing. Mint one token per device, send it as{" "}
              <code>Authorization: Bearer &lt;token&gt;</code>.
            </p>
            {tokenError && <div className="alert error">{tokenError}</div>}
            {mintedToken && (
              <div className="alert success" style={{ wordBreak: "break-all" }}>
                Token <b>{mintedToken.label || "unnamed"}</b> minted — copy it now, it is <b>shown only once</b>:
                <div className="mono" style={{ marginTop: 6, userSelect: "all" }}>
                  {mintedToken.token}
                </div>
                <div className="mono small" style={{ marginTop: 6, userSelect: "all" }}>
                  {`curl -X POST ${window.location.origin}/ingest/sensor-chunk -H "Authorization: Bearer ${mintedToken.token}" -H "Content-Type: application/json" -d '{"channel":"eda","unit":"uS","seq":0,"batch_started_wall":"2026-01-01T00:00:00Z","samples":[{"t_wall":"2026-01-01T00:00:00.100Z","value":0.42}]}'`}
                </div>
              </div>
            )}
            {recording.participants.map((p) => (
              <div key={p.id} style={{ marginBottom: 18 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
                  <strong className="mono small">{p.anon_id}</strong>
                  <input
                    placeholder="Token label (e.g. Empatica E4 rig)"
                    value={tokenLabel[p.id] || ""}
                    onChange={(e) => setTokenLabel((t) => ({ ...t, [p.id]: e.target.value }))}
                    style={{ maxWidth: 260 }}
                  />
                  <button type="button" className="btn primary" onClick={() => onMintToken(p.id)}>
                    + Mint token
                  </button>
                </div>
                <table className="data compact">
                  <thead>
                    <tr>
                      <th>Label</th>
                      <th>Token prefix</th>
                      <th>Created</th>
                      <th>Last used</th>
                      <th>Status</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {(sensorTokens[p.id] || []).map((t) => (
                      <tr key={t.id}>
                        <td>{t.label}</td>
                        <td className="mono small">{t.prefix}…</td>
                        <td className="small muted">
                          {new Date(t.created_at).toLocaleString()} · {t.created_by}
                        </td>
                        <td className="small muted">{t.last_used_at ? new Date(t.last_used_at).toLocaleString() : "never"}</td>
                        <td>{t.revoked ? <span className="chip error">revoked</span> : <span className="chip ok">active</span>}</td>
                        <td>
                          {!t.revoked && (
                            <button type="button" className="btn ghost" onClick={() => setConfirmRevokeToken({ participantId: p.id, token: t })}>
                              Revoke
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                    {(sensorTokens[p.id] || []).length === 0 && (
                      <tr>
                        <td colSpan={6} className="muted">
                          No tokens yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            ))}
          </>
        )}
      </div>

      <div className="card">
        <h2>Per-task results</h2>
        <table className="data compact">
          <thead>
            <tr>
              <th>Participant</th>
              <th>Task</th>
              <th>Duration</th>
              <th>Answer</th>
              <th>Score</th>
              <th>Events</th>
            </tr>
          </thead>
          <tbody>
            {recording.per_task.map((r, i) => (
              <tr key={i}>
                <td className="mono small">
                  <Link to={`/participants/${r.participant_id}`} title="Open this participant's full journey">
                    {r.participant_anon}
                  </Link>
                </td>
                <td className="mono small">{r.task_id}</td>
                <td>{r.duration_ms ? `${Math.round(r.duration_ms / 1000)}s` : "—"}</td>
                <td className="mono small" style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.answer !== null && r.answer !== undefined ? JSON.stringify(r.answer) : undefined}>
                  {r.answer !== null && r.answer !== undefined ? JSON.stringify(r.answer) : "—"}
                </td>
                <td>{r.score ?? "—"}</td>
                <td>{r.n_events_total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Tags</h2>
        <form onSubmit={onSaveTags} style={{ display: "flex", gap: 10 }}>
          <input type="text" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="comma, separated, tags" style={{ flex: 1 }} />
          <button type="submit" className="btn">
            Save
          </button>
        </form>
      </div>

      <div className="card">
        <h2>Notes</h2>
        <ul style={{ listStyle: "none", padding: 0, margin: "0 0 14px", display: "flex", flexDirection: "column", gap: 8 }}>
          {(session.notes || []).map((n, i) => (
            <li key={i} className="small">
              <span className="muted">{n.wall_clock}</span> <strong>{n.author}</strong>: {n.text}
            </li>
          ))}
          {(session.notes || []).length === 0 && <li className="muted small">No notes yet.</li>}
        </ul>
        <form onSubmit={onAddNote} style={{ display: "flex", gap: 10 }}>
          <input type="text" value={noteText} onChange={(e) => setNoteText(e.target.value)} placeholder="Add a note…" style={{ flex: 1 }} />
          <button type="submit" className="btn">
            Add
          </button>
        </form>
      </div>

      <div className="card">
        <h2>Recent events</h2>
        <table className="data compact">
          <thead>
            <tr>
              <th>t_ms</th>
              <th>Source</th>
              <th>Type</th>
              <th>Task</th>
            </tr>
          </thead>
          <tbody>
            {recording.events.slice(-100).map((e, i) => (
              <tr key={i}>
                <td className="mono small">{e.t_ms}</td>
                <td>
                  <span className={`chip src-${e.source}`}>{e.source}</span>
                </td>
                <td className="mono small">{e.type}</td>
                <td className="mono small">{e.task_id ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
