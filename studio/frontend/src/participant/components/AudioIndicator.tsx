import type { AudioIndicatorState } from "../hooks/useAudioRecorder";

const LABELS: Record<AudioIndicatorState, string> = {
  idle: "",
  requesting: "Requesting microphone…",
  recording: "Recording",
  denied: "Microphone blocked",
  unsupported: "Audio not supported by this browser",
  error: "Recorder error",
};

export function AudioIndicator({ state, queuedCount }: { state: AudioIndicatorState; queuedCount: number }) {
  if (state === "idle") return null;
  const label = state === "recording" && queuedCount > 0 ? `Recording · ${queuedCount} queued` : LABELS[state];
  return (
    <div className="audio-indicator" data-state={state}>
      <span className="audio-dot" />
      <span className="audio-label">{label}</span>
    </div>
  );
}
