import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { apiGet } from "../../lib/api";
import type { CompareResponse } from "../types";

function fmtMs(ms: number | null | undefined): string {
  if (!ms) return "—";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}.${Math.floor((ms % 1000) / 100)}s`;
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

const PALETTE = ["#2563eb", "#16a34a", "#0ea5e9"];

export function ComparePage() {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<CompareResponse | null>(null);
  const [selected, setSelected] = useState<string[]>(params.get("studies")?.split(",").filter(Boolean) ?? []);
  const [taskId, setTaskId] = useState(params.get("task_id") ?? "");

  async function load() {
    const qs = params.toString();
    const res = await apiGet<CompareResponse>(`/api/admin/compare${qs ? `?${qs}` : ""}`);
    setData(res);
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const next = new URLSearchParams();
    if (selected.length) next.set("studies", selected.join(","));
    if (taskId) next.set("task_id", taskId);
    setParams(next);
  }

  if (!data) return <p className="muted">Loading…</p>;
  const payload = data.payload;
  const inf = payload?.inference;
  const showInference = payload && inf && payload.rows.length === 2;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Compare studies</h1>
          <p className="muted small">A/B two studies side by side — e.g. the same task run with vs without the AI advisor.</p>
        </div>
      </div>

      <section className="card">
        <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <label className="field">
            Studies <span className="muted small">(Ctrl/Cmd to multi-select)</span>
            <select
              multiple
              size={8}
              style={{ minHeight: 160 }}
              value={selected}
              onChange={(e) => setSelected(Array.from(e.target.selectedOptions).map((o) => o.value))}
            >
              {data.all_studies.map((s) => (
                <option key={s.slug} value={s.slug}>
                  {s.name} — {s.mode}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Shared task (optional)
            {data.shared_task_ids.length > 0 ? (
              <select value={taskId} onChange={(e) => setTaskId(e.target.value)}>
                <option value="">— summary only —</option>
                {data.shared_task_ids.map((tid) => (
                  <option key={tid} value={tid}>
                    {tid}
                  </option>
                ))}
              </select>
            ) : (
              <input type="text" value={taskId} onChange={(e) => setTaskId(e.target.value)} placeholder="e.g. ex1-find-mpg" />
            )}
          </label>
          <button type="submit" className="btn primary" style={{ alignSelf: "flex-start" }}>
            Compare
          </button>
        </form>
      </section>

      {showInference && (
        <section className="card">
          <h2>
            Result · time on <code>{payload.task_id}</code>
          </h2>
          {inf.welch.p_two_sided !== null && (
            <p>
              p {inf.welch.p_two_sided < 0.001 ? "< 0.001" : `= ${inf.welch.p_two_sided.toFixed(3)}`}
              {inf.cohens_d !== null && ` · Cohen's d = ${inf.cohens_d.toFixed(2)}`} · n = {inf.n_a}, {inf.n_b}
            </p>
          )}
        </section>
      )}

      {payload && payload.rows.length > 0 && (
        <section className="card">
          <h2>{payload.task_id ? "Per-study results" : "Study summaries"}</h2>
          <table className="data compact">
            <thead>
              <tr>
                <th>Study</th>
                {payload.task_id ? (
                  <>
                    <th>Runs</th>
                    <th>Mean duration</th>
                    <th>Correct rate</th>
                  </>
                ) : (
                  <>
                    <th>Sessions</th>
                    <th>Completed</th>
                    <th>Participants</th>
                    <th>Completion rate</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {payload.rows.map((row, i) => (
                <tr key={row.study.slug}>
                  <td>
                    <span className="dot" style={{ background: PALETTE[i % 3] }} /> {row.study.name}
                  </td>
                  {payload.task_id ? (
                    <>
                      <td>{row.n_runs}</td>
                      <td>{fmtMs(row.mean_duration_ms)}</td>
                      <td>{row.correct_rate != null ? `${Math.round(row.correct_rate * 100)}%` : "—"}</td>
                    </>
                  ) : (
                    <>
                      <td>{row.n_sessions}</td>
                      <td>{row.n_sessions_completed}</td>
                      <td>{row.n_participants}</td>
                      <td>{row.completion_rate != null ? `${Math.round(row.completion_rate * 100)}%` : "—"}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
