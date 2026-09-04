import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiGet, apiPost } from "../../lib/api";
import type { Participant, Study } from "../../lib/types";
import { BiometricIndicator } from "../components/BiometricIndicator";
import { useHeartRateMonitor } from "../hooks/useHeartRateMonitor";
import { useScreenRecorder } from "../hooks/useScreenRecorder";
import "../../styles/task.css";

interface RunShellResponse {
  next?: string;
  participant?: Participant;
  study?: Study;
}

export function RunShellPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<RunShellResponse | null>(null);
  const [innerSrc, setInnerSrc] = useState<string | null>(null);
  const [declined, setDeclined] = useState(false);
  const { state, error, supported, start } = useScreenRecorder();
  const heartRate = useHeartRateMonitor();

  useEffect(() => {
    apiGet<RunShellResponse>("/api/p/run").then((res) => {
      if (res.next) {
        navigate(res.next, { replace: true });
        return;
      }
      setData(res);
    });
  }, [navigate]);

  const wantMic = ((data?.study?.recording?.audio as string | undefined) ?? "none") !== "none";

  async function onStart() {
    try {
      await start(wantMic);
      setInnerSrc("/p/resume");
    } catch {
      // error state already surfaced by the hook
    }
  }

  async function onDeclineContinue() {
    const res = await apiPost<{ next?: string }>("/api/p/run/decline", { choice: "continue" });
    setDeclined(true);
    setInnerSrc(res.next ?? "/p/resume");
  }

  async function onDeclineEnd() {
    const res = await apiPost<{ next?: string }>("/api/p/run/decline", { choice: "end" });
    window.location.href = res.next ?? "/p/finish";
  }

  if (!data) return null;
  const { study } = data;
  const showOverlay = !innerSrc || (state !== "recording" && !declined);
  const indicatorState = state === "recording" ? "recording" : state === "stopped" || state === "error" ? "stopped" : "idle";
  const indicatorLabel = state === "recording" ? "Recording" : state === "stopped" ? "Recording stopped" : "Not recording";

  return (
    <div className="rec-shell">
      <div className="rec-indicator" data-state={indicatorState}>
        <span className="rec-dot" />
        <span className="rec-label">{indicatorLabel}</span>
      </div>
      {!!study?.recording?.biometric && <BiometricIndicator status={heartRate.status} bpm={heartRate.bpm} />}

      {showOverlay && (
        <div className="rec-overlay">
          <main className="p-card rec-card">
            <p className="muted small p-eyebrow">Recording</p>
            <h1 style={{ marginTop: 4 }}>{study?.name}</h1>
            <p style={{ marginTop: 16, lineHeight: 1.6 }}>
              This session will be <strong>{wantMic ? "screen and microphone recorded" : "screen recorded"}</strong>{" "}
              for research analysis. When you click below, your browser will ask which screen or tab to share —
              please choose <strong>&ldquo;This Tab&rdquo;</strong>
              {wantMic ? " and keep your microphone on" : ""}.
            </p>
            <p className="muted small" style={{ marginTop: 10 }}>
              The recording is stored securely and is only viewable by the research team.
            </p>
            <button
              type="button"
              className="btn primary"
              style={{ marginTop: 20, padding: "11px 20px" }}
              disabled={!supported || state === "requesting"}
              onClick={onStart}
            >
              Start recording &amp; begin →
            </button>
            {error && (
              <div className="rec-error">
                {error}
                <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "center" }}>
                  <button type="button" className="btn ghost" onClick={onDeclineContinue}>
                    Continue without recording
                  </button>
                  <button type="button" className="btn ghost" onClick={onDeclineEnd}>
                    End my participation
                  </button>
                </div>
              </div>
            )}
          </main>
        </div>
      )}

      {innerSrc && (
        <div className="rec-inner-wrap" style={{ display: state === "recording" || declined ? "block" : "none" }}>
          <iframe
            className="rec-inner-frame"
            title={study?.name}
            src={innerSrc}
            allow="fullscreen; microphone; camera; display-capture"
          />
        </div>
      )}
    </div>
  );
}
