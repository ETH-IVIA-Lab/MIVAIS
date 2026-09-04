import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiGet, apiPost } from "../../lib/api";
import type { BiometricResponse, NextResponse } from "../../lib/types";
import { ParticipantCard } from "../components/ParticipantCard";
import { useHeartRateMonitor } from "../hooks/useHeartRateMonitor";

export function BiometricPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<BiometricResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { status, bpm, supported, connect } = useHeartRateMonitor();

  useEffect(() => {
    apiGet<BiometricResponse>("/api/p/biometric").then((res) => {
      if (res.next) {
        navigate(res.next, { replace: true });
        return;
      }
      setData(res);
    });
  }, [navigate]);

  async function submit(biometricStatus: "connected" | "skipped" | "unsupported") {
    setBusy(true);
    try {
      const res = await apiPost<NextResponse>("/api/p/biometric", { status: biometricStatus });
      navigate(res.next ?? "/", { replace: true });
    } finally {
      setBusy(false);
    }
  }

  async function onConnect() {
    setError(null);
    try {
      await connect();
      await submit("connected");
    } catch {
      setError("Couldn't connect to a heart-rate monitor. You can skip this and continue.");
    }
  }

  if (!data || !data.study) {
    return (
      <ParticipantCard wide>
        <p className="muted">Loading…</p>
      </ParticipantCard>
    );
  }

  return (
    <ParticipantCard wide>
      <p className="muted small p-eyebrow">Heart-rate monitor</p>
      <h1 style={{ marginTop: 4 }}>{data.study.name}</h1>

      {supported ? (
        <>
          <p className="p-prose">
            This study can record your heart rate alongside your other activity. If you have a Bluetooth heart-rate
            strap or fitness tracker, click below and choose it from your browser's device picker. This step is{" "}
            <strong>optional</strong> — you can skip it and continue either way.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              onConnect();
            }}
            style={{ marginTop: 28, display: "flex", gap: 10 }}
          >
            <button type="submit" className="btn primary" disabled={busy || status === "connecting"} style={{ padding: "10px 18px" }}>
              {status === "connecting" ? "Connecting…" : "Connect heart-rate monitor"}
            </button>
            <button type="button" className="btn ghost" disabled={busy} onClick={() => submit("skipped")}>
              Skip
            </button>
          </form>
          {error && <div className="rec-error" style={{ marginTop: 12 }}>{error}</div>}
          {status === "connected" && bpm != null && (
            <p className="muted small" style={{ marginTop: 12 }}>
              Connected — reading {bpm} bpm.
            </p>
          )}
        </>
      ) : (
        <>
          <p className="p-prose">
            This study can record heart-rate data, but your browser doesn't support connecting Bluetooth devices.
            You can continue without it.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit("unsupported");
            }}
            style={{ marginTop: 28, display: "flex", gap: 10 }}
          >
            <button type="submit" className="btn primary" disabled={busy} style={{ padding: "10px 18px" }}>
              Continue →
            </button>
          </form>
        </>
      )}
    </ParticipantCard>
  );
}
