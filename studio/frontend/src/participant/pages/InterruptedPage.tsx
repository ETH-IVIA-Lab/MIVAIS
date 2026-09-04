import { Link } from "react-router-dom";
import { ParticipantCard } from "../components/ParticipantCard";

export function InterruptedView() {
  return (
    <ParticipantCard centered>
      <div className="p-icon-circle warn">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 8v5M12 16h.01" />
        </svg>
      </div>
      <h1 style={{ marginTop: 0 }}>This session was interrupted</h1>
      <p>
        The study platform restarted while your session was active, and the visual analytics system did not
        survive. Your answers so far have been kept.
      </p>
      <p className="muted small" style={{ marginTop: 12 }}>
        Ask your researcher for a new access code to start a fresh session.
      </p>
      <Link to="/" className="btn primary" style={{ marginTop: 18 }}>
        Back to start
      </Link>
    </ParticipantCard>
  );
}
