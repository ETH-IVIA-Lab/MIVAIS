import type { HRStatus } from "../lib/heartRateMonitor";

const LABELS: Record<HRStatus, string> = {
  idle: "",
  connecting: "Connecting to heart-rate monitor…",
  connected: "Connected",
  disconnected: "Heart-rate monitor disconnected",
  denied: "Heart-rate monitor not connected",
  unsupported: "Heart-rate monitor not supported by this browser",
  error: "Heart-rate monitor error",
};

export function BiometricIndicator({ status, bpm }: { status: HRStatus; bpm: number | null }) {
  if (status === "idle") return null;
  const label = status === "connected" && bpm != null ? `${bpm} bpm` : LABELS[status];
  return (
    <div className="biometric-indicator" data-state={status}>
      <span className="biometric-heart">♥</span>
      <span className="audio-label">{label}</span>
    </div>
  );
}
