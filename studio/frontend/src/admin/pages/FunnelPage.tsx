import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet } from "../../lib/api";
import type { FunnelResponse } from "../types";

export function FunnelPage() {
  const { slug = "" } = useParams();
  const [data, setData] = useState<FunnelResponse | null>(null);

  useEffect(() => {
    apiGet<FunnelResponse>(`/api/admin/studies/${slug}/funnel`).then(setData);
  }, [slug]);

  if (!data) return <p className="muted">Loading…</p>;
  const top = data.stages[0]?.count || 1;

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="breadcrumb">
            <Link to={`/studies/${slug}`}>{data.study.name}</Link> / Funnel
          </div>
          <h1>Drop-off funnel</h1>
          <p className="muted small">How many participants reached each milestone.</p>
        </div>
      </div>

      <section className="card">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {data.stages.map((st) => (
            <div key={st.name} style={{ display: "grid", gridTemplateColumns: "200px 1fr 90px", alignItems: "center", gap: 12 }}>
              <span className={st._alt ? "muted small" : undefined}>{st.name}</span>
              <div style={{ background: "var(--bg-soft)", height: 22, borderRadius: 4, overflow: "hidden" }}>
                <div
                  style={{
                    background: st._alt ? "var(--error)" : "var(--accent)",
                    height: "100%",
                    width: `${((st.count / top) * 100).toFixed(1)}%`,
                  }}
                />
              </div>
              <span className="mono small" style={{ textAlign: "right" }}>
                {st.count} <span className="muted">({Math.round(st.pct)}%)</span>
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
