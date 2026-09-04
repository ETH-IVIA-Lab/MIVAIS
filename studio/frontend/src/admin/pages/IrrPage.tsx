import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiGet } from "../../lib/api";
import type { IrrResponse } from "../types";

const BAND_COLORS = ["#dc2626", "#d97706", "#ca8a04", "#65a30d", "#16a34a"];

function kappaColor(k: number): string {
  if (k < 0.2) return BAND_COLORS[0];
  if (k < 0.4) return BAND_COLORS[1];
  if (k < 0.6) return BAND_COLORS[2];
  if (k < 0.8) return BAND_COLORS[3];
  return BAND_COLORS[4];
}

export function IrrPage() {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<IrrResponse | null>(null);

  async function load() {
    const qs = params.toString();
    const res = await apiGet<IrrResponse>(`/api/admin/irr${qs ? `?${qs}` : ""}`);
    setData(res);
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  function update(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  }

  if (!data) return <p className="muted">Loading…</p>;
  const k = data.result?.kappa ?? null;
  const mpos = k !== null ? Math.round(Math.max(0, k) * 100 * 10) / 10 : 0;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Inter-rater reliability</h1>
          <p className="muted small">
            Did two users who tagged the same sessions agree? Cohen&apos;s κ measures their agreement, corrected for chance.
          </p>
        </div>
      </div>

      <section className="card compact">
        <b>Use case: reliable qualitative coding of sessions.</b>
        <p className="muted small" style={{ margin: "6px 0 0" }}>
          You watched every replay and tagged sessions with codes like <code>confused</code>, <code>aha-moment</code>, or{" "}
          <code>ignored-agent</code> — but before those codes go into a paper, they must not depend on who did the
          coding. Have a second user independently replay the same sessions and apply the same tag vocabulary (Tags
          box on the session detail page — each user&apos;s tags are stored separately). Then pick the tag and the two
          users here: κ ≥ 0.8 means the code is reliable as defined; lower values mean the codebook needs sharper
          definitions before the disputed sessions are re-coded. Example: in a think-aloud study on demo-proactiveva,
          two users tag which sessions <code>ignored-agent</code> — κ tells you whether &quot;ignoring the assistant&quot;
          was defined crisply enough to be an actual finding.
        </p>
      </section>

      <section className="card">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, alignItems: "end" }}>
          <label className="field">
            Study (optional)
            <select value={params.get("study") ?? ""} onChange={(e) => update("study", e.target.value)}>
              <option value="">All studies</option>
              {data.all_studies.map((s) => (
                <option key={s.slug} value={s.slug}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Tag
            <select value={params.get("tag") ?? ""} onChange={(e) => update("tag", e.target.value)}>
              <option value="">—</option>
              {data.all_tags.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            User A
            <select value={params.get("a") ?? ""} onChange={(e) => update("a", e.target.value)}>
              <option value="">—</option>
              {data.raters.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            User B
            <select value={params.get("b") ?? ""} onChange={(e) => update("b", e.target.value)}>
              <option value="">—</option>
              {data.raters.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      {data.result && k !== null && (
        <section className="card">
          <p>
            <code>{data.result.a}</code> and <code>{data.result.b}</code> both tagged <strong>{data.result.paired_n}</strong> of the same
            sessions for <code>{data.result.tag}</code>. They agreed <strong>{Math.round(data.result.agreement * 100)}%</strong> of the
            time — after correcting for chance, that is{" "}
            <strong style={{ color: kappaColor(k) }}>{data.result.interpretation}</strong> agreement.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 24, alignItems: "center" }}>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: "3rem", fontWeight: 800, color: kappaColor(k) }}>{k.toFixed(2)}</div>
              <span style={{ display: "inline-block", padding: "3px 12px", borderRadius: 999, fontSize: "0.85rem", fontWeight: 600, color: "#fff", background: kappaColor(k) }}>
                {data.result.interpretation}
              </span>
              <div className="muted small" style={{ marginTop: 4 }}>
                Cohen&apos;s κ
              </div>
            </div>
            <div style={{ position: "relative", paddingTop: 24 }}>
              <div style={{ display: "flex", height: 20, borderRadius: 6, overflow: "hidden" }}>
                {BAND_COLORS.map((c) => (
                  <span key={c} style={{ flex: 1, background: c }} />
                ))}
              </div>
              <div style={{ position: "absolute", top: 18, left: `${mpos}%`, height: 26, borderLeft: "2px solid var(--ink)" }} />
            </div>
          </div>
          <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginTop: 18 }}>
            <div className="small muted">
              <b style={{ display: "block", fontSize: "1.35rem", color: "var(--ink)" }}>{Math.round(data.result.agreement * 100)}%</b>
              observed agreement
            </div>
            <div className="small muted">
              <b style={{ display: "block", fontSize: "1.35rem", color: "var(--ink)" }}>{Math.round(data.result.expected * 100)}%</b>
              expected by chance
            </div>
            <div className="small muted">
              <b style={{ display: "block", fontSize: "1.35rem", color: "var(--ink)" }}>{data.result.paired_n}</b>
              sessions both users tagged
            </div>
          </div>
        </section>
      )}
      {data.result && k === null && (
        <div className="alert">
          Not enough paired tags to compute κ — only {data.result.paired_n} session(s) were tagged by both users.
        </div>
      )}
      {!data.raters.length && (
        <div className="alert">
          No paired tags yet. A session becomes eligible for κ once two different users each tag it (via the Tags box on a
          session&apos;s detail page).
        </div>
      )}
    </div>
  );
}
