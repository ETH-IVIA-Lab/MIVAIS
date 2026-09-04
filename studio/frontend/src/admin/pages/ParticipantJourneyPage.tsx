import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet } from "../../lib/api";
import type { ParticipantJourneyResponse } from "../types";

function fmtMs(ms: number | null): string {
  if (!ms) return "—";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}.${Math.floor((ms % 1000) / 100)}s`;
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

export function ParticipantJourneyPage() {
  const { id = "" } = useParams();
  const [data, setData] = useState<ParticipantJourneyResponse | null>(null);

  useEffect(() => {
    apiGet<ParticipantJourneyResponse>(`/api/admin/participants/${id}`).then(setData);
  }, [id]);

  if (!data) return <p className="muted">Loading…</p>;
  const { payload } = data;
  const { participant: p, study, session } = payload;
  const nCorrect = payload.task_runs.filter((r) => r.correct === true).length;
  const nIncorrect = payload.task_runs.filter((r) => r.correct === false).length;

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="breadcrumb">
            {study && <Link to={`/studies/${study.slug}`}>{study.name}</Link>}
            {session && <> / <Link to={`/sessions/${session.id}`}>Session</Link></>} / Participant
          </div>
          <h1>{p.anon_id}</h1>
          <p className="muted small mono">
            {p.id} {p.role && <span className="chip role">{p.role}</span>} <span className="chip">{p.status}</span>
            {p.external_id && <span className="muted small"> ext id {p.external_id}</span>}
          </p>
        </div>
      </div>

      <section className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Task runs</div>
          <div className="stat-value">{payload.task_runs.length}</div>
          <div className="stat-sub muted">
            {nCorrect} correct · {nIncorrect} incorrect
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Events recorded</div>
          <div className="stat-value">{payload.n_events}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Transcripts</div>
          <div className="stat-value">{payload.transcripts.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Joined / Finished</div>
          <div className="stat-value mono small">
            {new Date(p.joined_at).toLocaleTimeString()} → {p.finished_at ? new Date(p.finished_at).toLocaleTimeString() : "—"}
          </div>
        </div>
      </section>

      {p.applied_task_order.length > 0 && (
        <section className="card">
          <h2>Task order this participant saw</h2>
          <p className="muted small">
            {p.shuffle_seed ? (
              <>
                Counterbalanced — seed <code>{p.shuffle_seed}</code>.
              </>
            ) : (
              "Declared order (no counterbalancing applied)."
            )}
          </p>
          <ol className="mono small" style={{ lineHeight: 1.8 }}>
            {p.applied_task_order.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ol>
        </section>
      )}

      <section className="card">
        <h2>Task-by-task journey</h2>
        <table className="data">
          <thead>
            <tr>
              <th>#</th>
              <th>Task</th>
              <th>Duration</th>
              <th>Answer</th>
              <th>Score</th>
              <th>Correct</th>
              <th>Events</th>
              <th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {payload.task_runs.map((r) => (
              <tr key={r.task_index}>
                <td className="muted small">{r.task_index + 1}</td>
                <td>
                  <code>{r.task_id}</code>
                </td>
                <td>{fmtMs(r.duration_ms)}</td>
                <td className="mono small">{r.answer !== null && r.answer !== undefined ? JSON.stringify(r.answer).slice(0, 60) : "—"}</td>
                <td>{r.score !== null ? r.score.toFixed(2) : "—"}</td>
                <td>
                  {r.correct === true && <span className="chip ok">✓</span>}
                  {r.correct === false && <span className="chip error">✗</span>}
                  {r.correct === null && "—"}
                </td>
                <td className="muted small">
                  {r.n_events} ({r.n_mivais}M·{r.n_studio}S)
                </td>
                <td>
                  {r.timed_out && <span className="chip warn">timeout</span>}
                  {r.skipped && <span className="chip">skip</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {payload.transcripts.length > 0 && (
        <section className="card">
          <h2>What they said</h2>
          <div style={{ maxHeight: 360, overflowY: "auto" }}>
            {payload.transcripts.map((t, i) => (
              <div key={i} style={{ padding: "8px 10px", borderBottom: "1px dashed var(--line)" }}>
                <div className="muted small">
                  {(t.t_ms_start / 1000).toFixed(1)}s · {t.language ?? "—"}
                </div>
                <div>{t.text}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {payload.final_state && (
        <section className="card">
          <h2>Final WorldState (this participant)</h2>
          <pre className="mono small" style={{ whiteSpace: "pre-wrap", overflow: "auto", maxHeight: 400 }}>
            {JSON.stringify(payload.final_state, null, 2).slice(0, 3500)}
          </pre>
        </section>
      )}
    </div>
  );
}
