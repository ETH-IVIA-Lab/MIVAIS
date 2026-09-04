import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiDelete, apiGet, ApiError } from "../../lib/api";
import type { SessionsIndexResponse } from "../types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { TrashIcon } from "../components/icons";

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function SessionsPage() {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<SessionsIndexResponse | null>(null);

  const studyFilter = params.get("study") ?? "";
  const statusFilter = params.get("status") ?? "";
  const tagFilter = params.get("tag") ?? "";

  const [flash, setFlash] = useState<string | null>(null);
  const [confirmSession, setConfirmSession] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function onDeleteSession() {
    const id = confirmSession;
    if (!id) return;
    setDeleting(true);
    try {
      const res = await apiDelete<{ message?: string }>(`/api/admin/sessions/${id}`);
      setFlash(res?.message ?? "Session deleted");
      setConfirmSession(null);
      await load();
    } catch (err) {
      setFlash(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setDeleting(false);
    }
  }

  async function load() {
    const qs = params.toString();
    const res = await apiGet<SessionsIndexResponse>(`/api/admin/sessions${qs ? `?${qs}` : ""}`);
    setData(res);
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  function updateFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  }

  if (!data) return <p className="muted">Loading…</p>;

  return (
    <div>
      <div className="page-head">
        <h1>Sessions</h1>
      </div>

      <div className="card compact" style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
        <label className="field" style={{ maxWidth: 220 }}>
          Study
          <select value={studyFilter} onChange={(e) => updateFilter("study", e.target.value)}>
            <option value="">All studies</option>
            {data.all_studies.map((s) => (
              <option key={s.slug} value={s.slug}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field" style={{ maxWidth: 180 }}>
          Status
          <select value={statusFilter} onChange={(e) => updateFilter("status", e.target.value)}>
            <option value="">Any status</option>
            {["pending", "lobby", "spawning", "running", "completed", "failed", "abandoned", "interrupted"].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="field" style={{ maxWidth: 180 }}>
          Tag
          <input type="text" list="all-tags" value={tagFilter} onChange={(e) => updateFilter("tag", e.target.value)} />
          <datalist id="all-tags">
            {data.all_tags.map((t) => (
              <option key={t} value={t} />
            ))}
          </datalist>
        </label>
      </div>

      <ConfirmDialog
        open={confirmSession !== null}
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
        onCancel={() => setConfirmSession(null)}
      />

      {flash && <div className="alert">{flash}</div>}

      <div className="card">
        <table className="data">
          <thead>
            <tr>
              <th>Session</th>
              <th>Study</th>
              <th>Mode</th>
              <th>Status</th>
              <th>Participants</th>
              <th>Started</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.session.id}>
                <td className="mono small">{row.session.id.slice(-10)}</td>
                <td>{row.study?.name ?? "—"}</td>
                <td>{row.session.mode}</td>
                <td>
                  <span className={`chip status-${row.session.status}`}>{row.session.status}</span>
                </td>
                <td>
                  {row.n_finished} / {row.n_participants}
                </td>
                <td className="small muted">{fmtDate(row.session.created_at)}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <Link to={`/sessions/${row.session.id}`} className="btn ghost">
                    View
                  </Link>{" "}
                  <button
                    type="button"
                    className="btn icon-danger"
                    aria-label="Delete session"
                    title="Delete this session and all of its data"
                    onClick={() => setConfirmSession(row.session.id)}
                  >
                    <TrashIcon />
                  </button>
                </td>
              </tr>
            ))}
            {data.rows.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  No sessions match this filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
