function fmtCountdown(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}:${String(r).padStart(2, "0")}` : `${r}s`;
}

export function CohortWaitingBanner({ secondsRemaining }: { secondsRemaining?: number | null }) {
  const hasEta = typeof secondsRemaining === "number";
  return (
    <div className="cohort-waiting-banner">
      <span className="pulse" />
      <span>
        You&apos;re done. Waiting for the rest of the cohort to finish this task
        {hasEta ? (
          <>
            {" "}
            — the researcher will release it, or it auto-advances in <strong>{fmtCountdown(secondsRemaining)}</strong>
          </>
        ) : (
          "…"
        )}
      </span>
    </div>
  );
}
