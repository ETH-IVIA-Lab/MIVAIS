import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { apiPost, ApiError } from "../../lib/api";
import type { NextResponse } from "../../lib/types";
import { ParticipantCard } from "../components/ParticipantCard";

export function LandingPage() {
  const navigate = useNavigate();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const qs = window.location.search;
      const data = await apiPost<NextResponse>(`/api/join${qs}`, { code });
      navigate(data.next ?? "/p/task");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ParticipantCard>
      <div className="p-brand">
        <span className="mark" />
        <strong>MIVAIS Studio</strong>
      </div>
      <h1>Join a study</h1>
      <p className="muted">Enter the code your researcher gave you.</p>

      {error && <div className="alert error">{error}</div>}

      <form onSubmit={onSubmit} autoComplete="off" className="form-card" style={{ marginTop: 18 }}>
        <input
          type="text"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="ABC123"
          autoFocus
          required
          maxLength={12}
          className="p-code-input"
        />
        <button type="submit" className="btn primary" disabled={busy} style={{ padding: "12px 16px" }}>
          Continue →
        </button>
      </form>

      <p className="muted small" style={{ marginTop: 20, textAlign: "center" }}>
        Got a question? Get in touch with the researcher who shared the code.
      </p>
    </ParticipantCard>
  );
}
