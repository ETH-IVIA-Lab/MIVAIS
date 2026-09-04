import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPatch, ApiError } from "../../lib/api";
import { StatusDonut } from "../components/StatusDonut";
import { TimeseriesChart } from "../components/TimeseriesChart";
import type { DashboardResponse } from "../types";

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export function DashboardPage() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const res = await apiGet<DashboardResponse>("/api/admin/");
    setData(res);
  }

  useEffect(() => {
    load();
  }, []);

  async function onArchiveToggle(slug: string, archived: boolean) {
    setError(null);
    try {
      await apiPatch(`/api/admin/studies/${slug}`, { archived: !archived });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  if (!data) return <p className="muted">Loading…</p>;

  const rows = showArchived ? data.per_study_archived : data.per_study;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Studies</h1>
        </div>
        <div className="head-actions">
          <Link to="/studies/new" className="btn primary">
            + Register a study
          </Link>
        </div>
      </div>

      {error && <div className="alert">{error}</div>}

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Studies</div>
          <div className="stat-value">{data.overview.n_studies}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Sessions</div>
          <div className="stat-value">{data.overview.n_sessions}</div>
          <div className="stat-sub muted">{data.overview.n_sessions_completed} completed</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Participants</div>
          <div className="stat-value">{data.overview.n_participants}</div>
          <div className="stat-sub muted">{data.overview.n_participants_finished} finished</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Completion rate</div>
          <div className="stat-value">{pct(data.overview.completion_rate)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Active now</div>
          <div className="stat-value">{data.extras.active_now}</div>
          <div className="stat-sub muted">{data.extras.sessions_today} today · {data.extras.sessions_7d} this week</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Avg. duration</div>
          <div className="stat-value">{data.extras.avg_duration_human}</div>
        </div>
      </div>

      <section className="chart-grid">
        <div className="card chart-card chart-wide">
          <div className="chart-head">
            <h3>Sessions, last 14 days</h3>
            <div className="chart-legend">
              <span>
                <span className="dot" style={{ background: "var(--ink)" }} /> total
              </span>
              <span>
                <span className="dot" style={{ background: "var(--success)" }} /> completed
              </span>
            </div>
          </div>
          <TimeseriesChart data={data.timeseries} />
        </div>
        <div className="card chart-card">
          <div className="chart-head">
            <h3>Session status</h3>
          </div>
          <StatusDonut data={data.status_breakdown} />
        </div>
      </section>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>{showArchived ? "Archived studies" : "Studies"}</h2>
          <button type="button" className="btn ghost" onClick={() => setShowArchived((v) => !v)}>
            {showArchived ? "Show active" : `Show archived (${data.per_study_archived.length})`}
          </button>
        </div>
        <table className="data" style={{ marginTop: 14 }}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Slug</th>
              <th>Mode</th>
              <th>Sessions</th>
              <th>Completed</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.study.slug}>
                <td>
                  <Link to={`/studies/${row.study.slug}`}>{row.study.name}</Link>
                </td>
                <td className="mono small">{row.study.slug}</td>
                <td>{row.study.mode}</td>
                <td>{row.n_sessions}</td>
                <td>{row.n_completed}</td>
                <td>
                  <button type="button" className="btn ghost" onClick={() => onArchiveToggle(row.study.slug, showArchived)}>
                    {showArchived ? "Restore" : "Archive"}
                  </button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  Nothing here yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
