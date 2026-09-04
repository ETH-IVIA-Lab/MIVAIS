import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet } from "../../lib/api";
import { RadarChart } from "../components/RadarChart";
import type { TaskDrilldownResponse } from "../types";

function fmtMs(ms: number | null): string {
  if (!ms) return "—";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}.${Math.floor((ms % 1000) / 100)}s`;
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export function TaskDrilldownPage() {
  const { slug = "", taskId = "" } = useParams();
  const [data, setData] = useState<TaskDrilldownResponse | null>(null);

  useEffect(() => {
    apiGet<TaskDrilldownResponse>(`/api/admin/studies/${slug}/task/${taskId}`).then(setData);
  }, [slug, taskId]);

  if (!data) return <p className="muted">Loading…</p>;
  const { payload } = data;
  const maxCount = Math.max(1, ...payload.duration_buckets.map((b) => b.count));

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="breadcrumb">
            <Link to="/">Studies</Link> / <Link to={`/studies/${slug}`}>{data.study.name}</Link> / Task drill-down
          </div>
          <h1>
            <code>{taskId}</code>
          </h1>
          {payload.task && <p className="muted small">{String(payload.task.type)}</p>}
        </div>
      </div>

      {!payload.task && (
        <div className="alert error">
          Task <code>{taskId}</code> does not exist in this study.
        </div>
      )}

      <section className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Runs</div>
          <div className="stat-value">{payload.n_runs}</div>
          <div className="stat-sub muted">
            {payload.n_timed_out} timed out · {payload.n_skipped} skipped
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Mean duration</div>
          <div className="stat-value">{fmtMs(payload.mean_duration_ms)}</div>
          <div className="stat-sub muted">median {fmtMs(payload.median_duration_ms)}</div>
        </div>
        {payload.n_with_score > 0 && (
          <div className="stat-card">
            <div className="stat-label">Correct rate</div>
            <div className="stat-value">{pct(payload.correct_rate)}</div>
            <div className="stat-sub muted">μ score {payload.mean_score.toFixed(2)}</div>
          </div>
        )}
      </section>

      {payload.distribution.length > 0 && (
        <section className="card">
          <h2>Answer distribution</h2>
          <div className="dist" style={{ maxWidth: 520 }}>
            {payload.distribution.map((row) => (
              <div key={row.label} className="dist-row">
                <span className="dist-label" title={row.label}>
                  {row.label}
                </span>
                <div className="dist-bar">
                  <div className="dist-bar-fill" style={{ width: `${row.percent}%` }} />
                </div>
                <span className="dist-count">{row.count}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {payload.duration_buckets.length > 0 && (
        <section className="card">
          <h2>Duration histogram</h2>
          <svg viewBox="0 0 600 140" style={{ width: "100%", maxWidth: 700, height: 140 }} role="img">
            {payload.duration_buckets.map((b, i) => {
              const n = payload.duration_buckets.length;
              const bw = 600 / n;
              const h = (b.count / maxCount) * 110;
              return (
                <rect key={i} x={i * bw + 2} y={120 - h} width={bw - 4} height={h} rx={2} fill="var(--color-brand-500)" opacity={0.85}>
                  <title>
                    {b.lo_ms}–{b.hi_ms} ms · {b.count}
                  </title>
                </rect>
              );
            })}
            <line x1={0} y1={120} x2={600} y2={120} stroke="var(--line)" strokeWidth={1} />
          </svg>
          <div className="muted small" style={{ display: "flex", justifyContent: "space-between" }}>
            <span>{fmtMs(payload.duration_buckets[0]?.lo_ms)}</span>
            <span>{fmtMs(payload.duration_buckets[payload.duration_buckets.length - 1]?.hi_ms)}</span>
          </div>
        </section>
      )}

      {payload.likert_heatmap && (
        <>
          <section className="card">
            <h2>Likert radar · cohort mean</h2>
            <RadarChart heatmap={payload.likert_heatmap} nRuns={payload.n_runs} />
          </section>
          <section className="card">
            <h2>Likert heatmap</h2>
            <div style={{ overflowX: "auto" }}>
              <table className="data" style={{ fontVariantNumeric: "tabular-nums" }}>
                <thead>
                  <tr>
                    <th>Item</th>
                    {Array.from(
                      { length: payload.likert_heatmap.scale_max - payload.likert_heatmap.scale_min + 1 },
                      (_, i) => payload.likert_heatmap!.scale_min + i,
                    ).map((v) => (
                      <th key={v} style={{ textAlign: "center", width: 36 }}>
                        {v}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {payload.likert_heatmap.items.map((item, i) => {
                    const rowMax = payload.likert_heatmap!.row_max[i] || 1;
                    return (
                      <tr key={item.id}>
                        <td>{item.label}</td>
                        {payload.likert_heatmap!.cells[i].map((cell, j) => {
                          const intensity = cell / rowMax;
                          return (
                            <td
                              key={j}
                              style={{
                                textAlign: "center",
                                background: `color-mix(in srgb, var(--color-brand-500) ${Math.round(intensity * 100)}%, transparent)`,
                                color: intensity > 0.55 ? "white" : "var(--ink)",
                              }}
                            >
                              {cell || "·"}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      <section className="card">
        <h2>All runs</h2>
        <table className="data compact">
          <thead>
            <tr>
              <th>Started</th>
              <th>Duration</th>
              <th>Answer</th>
              <th>Score</th>
              <th>Correct</th>
              <th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {payload.runs.map((r, i) => (
              <tr key={i}>
                <td className="muted small">{r.started_at ? new Date(r.started_at).toLocaleString() : "—"}</td>
                <td>{fmtMs(r.duration_ms)}</td>
                <td className="mono small">{r.answer !== null && r.answer !== undefined ? JSON.stringify(r.answer).slice(0, 80) : "—"}</td>
                <td>{r.score !== null ? r.score.toFixed(2) : "—"}</td>
                <td>
                  {r.correct === true && <span className="chip ok">✓</span>}
                  {r.correct === false && <span className="chip error">✗</span>}
                  {r.correct === null && "—"}
                </td>
                <td>
                  {r.timed_out && <span className="chip warn">timed out</span>}
                  {r.skipped && <span className="chip">skipped</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
