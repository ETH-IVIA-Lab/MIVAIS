import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet } from "../../lib/api";
import type { LivePollResponse, LiveSessionResponse } from "../types";

export function SessionLivePage() {
  const { id = "" } = useParams();
  const [info, setInfo] = useState<LiveSessionResponse | null>(null);
  const [poll, setPoll] = useState<LivePollResponse | null>(null);

  useEffect(() => {
    apiGet<LiveSessionResponse>(`/api/admin/sessions/${id}/live`).then(setInfo);
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const res = await apiGet<LivePollResponse>(`/api/admin/sessions/${id}/live/poll`);
        if (!cancelled) setPoll(res);
      } catch {
        // transient
      }
    };
    tick();
    const timer = setInterval(tick, 1500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [id]);

  if (!info) return <p className="muted">Loading…</p>;

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="breadcrumb">
            <Link to={`/studies/${info.study.slug}`}>{info.study.name}</Link> / <Link to={`/sessions/${id}`}>Session</Link> / Live
          </div>
          <h1>Live session</h1>
          <p className="muted small mono">
            {id} · <span className={`chip status-${poll?.session.status ?? info.session.status}`}>{poll?.session.status ?? info.session.status}</span> ·
            task {(poll?.session.current_task_index ?? info.session.current_task_index) + 1}
          </p>
        </div>
        <div className="head-actions">
          <Link to={`/sessions/${id}`} className="btn">
            View recording →
          </Link>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 20 }}>
        <div>
          <h2>Participants</h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
            {(poll?.participants ?? []).map((p) => (
              <div key={p.id} className="card compact">
                <div className="mono">{p.anon_id}</div>
                {p.role && (
                  <div style={{ marginTop: 4 }}>
                    <span className="chip role">{p.role}</span>
                  </div>
                )}
                <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 6 }}>
                  <span className={`chip status-${p.status}`}>{p.status}</span>
                  {p.current_task_id && <span className="chip">{p.current_task_id}</span>}
                </div>
                {p.checked_steps.length > 0 && <div className="muted small" style={{ marginTop: 8 }}>{p.checked_steps.length} step(s) done</div>}
              </div>
            ))}
            {(!poll || poll.participants.length === 0) && <p className="muted small">No participants yet.</p>}
          </div>

          <h2 style={{ marginTop: 22 }}>Audio</h2>
          <div className="card compact">
            <strong>{poll?.audio_chunks ?? 0}</strong> chunk(s) received · <strong>{poll?.transcripts ?? 0}</strong> transcribed
          </div>

          <h2 style={{ marginTop: 22 }}>Live transcript</h2>
          <div className="card" style={{ maxHeight: 280, overflowY: "auto" }}>
            {poll && poll.recent_transcripts.length > 0 ? (
              poll.recent_transcripts.map((seg, i) => (
                <div key={i} style={{ padding: "8px 10px", borderBottom: "1px dashed var(--line)" }}>
                  <div className="muted small">
                    {seg.t_ms_start ? `${(seg.t_ms_start / 1000).toFixed(1)}s` : "0s"} {seg.participant_anon && `· ${seg.participant_anon}`}{" "}
                    {seg.role && <span className="chip role">{seg.role}</span>} {seg.language && `· ${seg.language}`}
                  </div>
                  <div>{seg.text}</div>
                </div>
              ))
            ) : (
              <p className="muted small">No transcript yet.</p>
            )}
          </div>
        </div>

        <aside>
          <h2>Event stream</h2>
          <div className="card" style={{ maxHeight: 520, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
            {(poll?.events ?? []).map((e, i) => (
              <div key={i} className="small">
                <span className="mono muted">{e.t_ms}ms</span> <span className={`chip src-${e.source}`}>{e.source}</span>{" "}
                <span className="mono">{e.type}</span> {e.task_id && <span className="muted">· {e.task_id}</span>}
              </div>
            ))}
            {(!poll || poll.events.length === 0) && <p className="muted small">Waiting for events…</p>}
          </div>
        </aside>
      </div>

      {info.spectator_urls.length > 0 && (
        <section className="card" style={{ marginTop: 18 }}>
          <h2>Spectator view</h2>
          <p className="muted small">
            Live mirror via the studio_spectator role — strictly read-only: your clicks are dropped by the
            server, and participants cannot see you.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 14 }}>
            {info.spectator_urls.map((spec) => (
              <div key={spec.va_system_id}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span className="chip accent">VA · {spec.va_system_id}</span>
                  <a href={spec.url} target="_blank" rel="noopener noreferrer" className="muted small">
                    open in new tab
                  </a>
                </div>
                <iframe src={spec.url} title={spec.va_system_id} style={{ width: "100%", height: 320, border: "1px solid var(--line)", borderRadius: 8 }} />
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
