import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiDelete, apiGet, apiPatch, apiPost, ApiError } from "../../lib/api";
import type { StudyDetailResponse } from "../types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { TrashIcon } from "../components/icons";

interface StudyMetricAggregate {
  id: string;
  label: string;
  kind: string;
  unit: string;
  n_participants: number;
  mean: number | null;
  median: number | null;
  min: number | null;
  max: number | null;
}

interface StudyMetricsResponse {
  metrics: StudyMetricAggregate[];
  participants: unknown[];
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export function StudyDetailPage() {
  const { slug = "" } = useParams();
  const [data, setData] = useState<StudyDetailResponse | null>(null);
  const [newCode, setNewCode] = useState<string | null>(null);
  const [cohortCodes, setCohortCodes] = useState<{ code: string; role: string | null }[] | null>(null);
  const [roleInput, setRoleInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<StudyMetricsResponse | null>(null);

  const [confirmSession, setConfirmSession] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function onDeleteSession() {
    const id = confirmSession;
    if (!id) return;
    setDeleting(true);
    setMessage(null);
    try {
      const res = await apiDelete<{ message?: string }>(`/api/admin/sessions/${id}`);
      setMessage(res?.message ?? "Session deleted");
      setConfirmSession(null);
      await load();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setDeleting(false);
    }
  }

  async function load() {
    const res = await apiGet<StudyDetailResponse>(`/api/admin/studies/${slug}`);
    setData(res);
    // Behavioral metrics are lazy + optional: an empty response hides the card.
    apiGet<StudyMetricsResponse>(`/api/admin/studies/${slug}/metrics`)
      .then(setMetrics)
      .catch(() => setMetrics(null));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  async function onNewCode() {
    setBusy(true);
    setMessage(null);
    try {
      const res = await apiPost<{ ok: boolean; code: string }>(`/api/admin/studies/${slug}/codes`, {
        role: roleInput,
      });
      setNewCode(res.code);
      await load();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function onMintCohort() {
    if (!data) return;
    setBusy(true);
    setMessage(null);
    setCohortCodes(null);
    try {
      
      const roleIds = (data.study.roles || []).map((r) => r.id);
      const res = await apiPost<{ codes: string[] }>(`/api/admin/studies/${slug}/cohort`, {
        roles: roleIds.join(","),
      });
      setCohortCodes(res.codes.map((code, i) => ({ code, role: roleIds[i] ?? null })));
      await load();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function onToggleCode(codeId: string, active: boolean) {
    setMessage(null);
    try {
      await apiPatch(`/api/admin/codes/${codeId}`, { active: !active });
      await load();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  async function onArchiveToggle() {
    if (!data) return;
    const archiving = !data.study.archived;
    setMessage(null);
    try {
      await apiPatch(`/api/admin/studies/${slug}`, { archived: archiving });
      await load();
      setMessage(
        archiving
          ? "Study archived — it is hidden from the active list and no longer accepts new participants."
          : "Study restored — it is active again.",
      );
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  if (!data) return <p className="muted">Loading…</p>;
  const { study, codes, sessions, stats, tasks, share_base } = data;

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="breadcrumb">
            <Link to="/">Studies</Link> / {study.name}
          </div>
          <h1>
            {study.name}
            {study.archived && (
              <span
                className="chip warn"
                style={{ marginLeft: 10, verticalAlign: "middle" }}
                title="Hidden from the active list; new participants are rejected"
              >
                Archived
              </span>
            )}
          </h1>
          <p className="mono small muted">
            {study.slug} · {study.mode} · v{study.version}
          </p>
        </div>
        <div className="head-actions">
          <button type="button" className="btn primary" disabled={busy} onClick={onNewCode}>
            + New code
          </button>
          {study.mode === "multiplayer" && (
            <button
              type="button"
              className="btn primary"
              disabled={busy}
              title="Mint one code per role, all bound to the same lobby"
              onClick={onMintCohort}
            >
              + Mint cohort
            </button>
          )}
          <Link to={`/studies/${slug}/yaml`} className="btn ghost">
            Edit YAML
          </Link>
          <Link to={`/studies/${slug}/funnel`} className="btn ghost">
            Funnel
          </Link>
          <a className="btn ghost" href={`/api/admin/studies/${slug}/export.csv`}>
            CSV
          </a>
          <a className="btn ghost" href={`/api/admin/studies/${slug}/export.parquet`}>
            Parquet
          </a>
          <a className="btn ghost" href={`/api/admin/studies/${slug}/preregistration.json`}>
            Pre-reg
          </a>
          <button type="button" className={study.archived ? "btn ghost" : "btn danger"} onClick={onArchiveToggle}>
            {study.archived ? "Restore" : "Archive"}
          </button>
        </div>
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

      {message && <div className="alert">{message}</div>}
      {cohortCodes && (
        <div className="card compact" style={{ marginBottom: 16 }}>
          <strong>Cohort minted</strong> — all codes join the <em>same</em> lobby; hand one link to each participant:
          <table className="data" style={{ marginTop: 8 }}>
            <tbody>
              {cohortCodes.map((c) => (
                <tr key={c.code}>
                  <td>{c.role ? <span className="chip">{c.role}</span> : <span className="muted">any role</span>}</td>
                  <td className="mono">{c.code}</td>
                  <td className="mono small muted">
                    {share_base}/s/{c.code}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {newCode && (
        <div className="card compact" style={{ marginBottom: 16 }}>
          New code generated: <strong>{newCode}</strong>
          <div className="mono small muted" style={{ marginTop: 6 }}>
            {share_base}/s/{newCode}
          </div>
          
          {(study.completion_code || study.completion_redirect_url) && (
            <>
              <div className="small muted" style={{ marginTop: 10 }}>
                Recruiting on <strong>Prolific</strong>? Paste this as the study URL — Prolific fills
                in the placeholders, and Studio stores the PID on each participant for payment:
              </div>
              <div className="mono small" style={{ marginTop: 4, wordBreak: "break-all" }}>
                {`${share_base}/s/${newCode}?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}`}
              </div>
            </>
          )}
        </div>
      )}

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Sessions</div>
          <div className="stat-value">{stats.n_sessions}</div>
          <div className="stat-sub muted">{stats.n_sessions_completed} completed</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Participants</div>
          <div className="stat-value">{stats.n_participants}</div>
          <div className="stat-sub muted">{stats.n_participants_finished} finished</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Completion rate</div>
          <div className="stat-value">{pct(stats.completion_rate)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Mean session</div>
          <div className="stat-value">{stats.mean_duration_s ? `${Math.round(stats.mean_duration_s)}s` : "—"}</div>
          <div className="stat-sub muted">median {stats.median_duration_s ? `${Math.round(stats.median_duration_s)}s` : "—"}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Events</div>
          <div className="stat-value">{stats.n_events}</div>
          <div className="stat-sub muted">
            {stats.n_events_mivais} MIVAIS · {stats.n_events_studio} Studio
          </div>
        </div>
      </div>

      {metrics && metrics.metrics.length > 0 && (
        <div className="card">
          <h2>Behavioral metrics</h2>
          <p className="muted small">
            Declared in the study's <code>metrics:</code> block, computed per participant from the event stream.
            Aggregates across {metrics.participants.length} participant(s); also available at{" "}
            <code>/api/v1/studies/{slug}/metrics</code>.
          </p>
          <table className="data" style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>Metric</th>
                <th>Kind</th>
                <th>Median</th>
                <th>Mean</th>
                <th>Min</th>
                <th>Max</th>
                <th>n</th>
              </tr>
            </thead>
            <tbody>
              {metrics.metrics.map((m) => (
                <tr key={m.id}>
                  <td>
                    {m.label} <span className="mono small muted">{m.id}</span>
                  </td>
                  <td>
                    <span className="chip">{m.kind}</span> <span className="muted small">{m.unit}</span>
                  </td>
                  <td className="mono">{m.median ?? "—"}</td>
                  <td className="mono">{m.mean ?? "—"}</td>
                  <td className="mono">{m.min ?? "—"}</td>
                  <td className="mono">{m.max ?? "—"}</td>
                  <td className="mono">{m.n_participants}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card">
        <h2>Access codes</h2>
        <div className="form-card" style={{ flexDirection: "row", alignItems: "flex-end", gap: 10, maxWidth: "none" }}>
          <label className="field" style={{ maxWidth: 220 }}>
            Role (optional)
            <input type="text" value={roleInput} onChange={(e) => setRoleInput(e.target.value)} placeholder="e.g. analyst" />
          </label>
        </div>
        <table className="data" style={{ marginTop: 14 }}>
          <thead>
            <tr>
              <th>Code</th>
              <th>Role</th>
              <th>Uses</th>
              <th>Active</th>
              <th>Created</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {codes.map((c) => (
              <tr key={c.id}>
                <td className="mono">{c.code}</td>
                <td>{c.role ?? "—"}</td>
                <td>
                  {c.uses}
                  {c.max_uses ? ` / ${c.max_uses}` : ""}
                </td>
                <td>{c.active ? <span className="chip ok">active</span> : <span className="chip">disabled</span>}</td>
                <td className="small muted">{fmtDate(c.created_at)}</td>
                <td>
                  <button type="button" className="btn ghost" onClick={() => onToggleCode(c.id, c.active)}>
                    {c.active ? "Disable" : "Enable"}
                  </button>
                </td>
              </tr>
            ))}
            {codes.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  No codes yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Recent sessions</h2>
        <table className="data">
          <thead>
            <tr>
              <th>Session</th>
              <th>Mode</th>
              <th>Status</th>
              <th>Started</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.id}>
                <td className="mono small">{s.id.slice(-10)}</td>
                <td>{s.mode}</td>
                <td>
                  <span className={`chip status-${s.status}`}>{s.status}</span>
                </td>
                <td className="small muted">{fmtDate(s.created_at)}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <Link to={`/sessions/${s.id}`} className="btn ghost">
                    View
                  </Link>{" "}
                  <button
                    type="button"
                    className="btn icon-danger"
                    aria-label="Delete session"
                    title="Delete this session and all of its data"
                    onClick={() => setConfirmSession(s.id)}
                  >
                    <TrashIcon />
                  </button>
                </td>
              </tr>
            ))}
            {sessions.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No sessions yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Per-task summary</h2>
        <table className="data compact">
          <thead>
            <tr>
              <th>Task</th>
              <th>Type</th>
              <th>Block</th>
              <th>Runs</th>
              <th>Mean duration</th>
              <th>Correct rate</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.task_id}>
                <td className="mono small">
                  <Link to={`/studies/${slug}/task/${t.task_id}`}>{t.task_id}</Link>
                </td>
                <td>{t.type}</td>
                <td>{t.block_id}</td>
                <td>{t.n_runs}</td>
                <td>{t.mean_duration_ms ? `${Math.round(t.mean_duration_ms / 1000)}s` : "—"}</td>
                <td>{t.has_ground_truth ? pct(t.correct_rate) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
