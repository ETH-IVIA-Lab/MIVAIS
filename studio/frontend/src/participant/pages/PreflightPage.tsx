import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { apiGet } from "../../lib/api";
import type { PreflightResponse } from "../../lib/types";
import { ParticipantCard } from "../components/ParticipantCard";

type CheckState = boolean | null; 

function CheckItem({
  ok,
  label,
  okLabel,
  failLabel,
}: {
  ok: CheckState;
  label: string;
  okLabel: string;
  failLabel: string;
}) {
  const cls = ok === null ? "" : ok ? "ok" : "fail";
  const status = ok === null ? "checking…" : ok ? okLabel : failLabel;
  return (
    <li className={`check ${cls}`}>
      <span className="dot" />
      <span className="lbl">{label}</span>
      <span className="status">{status}</span>
    </li>
  );
}

export function PreflightPage() {
  const { code = "" } = useParams();
  const { search } = useLocation();
  const [data, setData] = useState<PreflightResponse | null>(null);
  const [browserOk, setBrowserOk] = useState<CheckState>(null);
  const [micState, setMicState] = useState<CheckState>(null);

  useEffect(() => {
    apiGet<PreflightResponse>(`/api/p/preflight/${encodeURIComponent(code)}`).then(setData);
  }, [code]);

  useEffect(() => {
    setBrowserOk(typeof window.fetch === "function" && typeof window.WebSocket === "function");
  }, []);

  useEffect(() => {
    if (!data?.audio_required) return;
    let cancelled = false;
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((t) => t.stop());
        if (!cancelled) setMicState(true);
      } catch {
        if (!cancelled) setMicState(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [data?.audio_required]);

  if (!data) {
    return (
      <ParticipantCard wide>
        <p className="muted">Loading…</p>
      </ParticipantCard>
    );
  }

  return (
    <ParticipantCard wide>
      <p className="muted small p-eyebrow">System check</p>
      <h1 style={{ marginTop: 4 }}>{data.study?.name ?? "Join a study"}</h1>
      <p className="muted">Before you join, we'll verify a few things your browser needs.</p>

      <ul className="check-list">
        <CheckItem ok={data.valid_code} label="Access code" okLabel="valid" failLabel="invalid or expired" />
        <CheckItem ok={browserOk} label="Browser support" okLabel="ok" failLabel="fetch/WebSocket missing" />
        {data.audio_required && (
          <CheckItem
            ok={micState}
            label="Microphone permission"
            okLabel="granted"
            failLabel="denied or unavailable"
          />
        )}
      </ul>

      <div style={{ display: "flex", gap: 10 }}>
        <Link
          to={`/s/${code}${search}`}
          className="btn primary"
          aria-disabled={!data.valid_code}
          onClick={(e) => {
            if (!data.valid_code) e.preventDefault();
          }}
        >
          Continue to study →
        </Link>
        <Link to="/" className="btn ghost">
          Back
        </Link>
      </div>
    </ParticipantCard>
  );
}
