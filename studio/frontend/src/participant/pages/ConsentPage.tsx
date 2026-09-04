import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiGet, apiPost } from "../../lib/api";
import type { ConsentResponse, NextResponse } from "../../lib/types";
import { ParticipantCard } from "../components/ParticipantCard";

const DEFAULT_CONSENT_HTML =
  "<p>By continuing, you agree to take part in this study. Your responses are recorded " +
  "anonymously under a short, generated identifier and are used for research purposes only. " +
  "You may close this tab at any time to withdraw.</p>";

export function ConsentPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<ConsentResponse | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiGet<ConsentResponse>("/api/p/consent").then((res) => {
      if (res.next) {
        navigate(res.next, { replace: true });
        return;
      }
      setData(res);
    });
  }, [navigate]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await apiPost<NextResponse>("/api/p/consent");
      navigate(res.next ?? "/", { replace: true });
    } finally {
      setBusy(false);
    }
  }

  if (!data || !data.study) {
    return (
      <ParticipantCard wide>
        <p className="muted">Loading…</p>
      </ParticipantCard>
    );
  }

  const { study } = data;
  const showVideoNotice = (study.recording?.video ?? "none") !== "none";
  const html = data.consent_html && data.consent_html.trim() ? data.consent_html : DEFAULT_CONSENT_HTML;

  return (
    <ParticipantCard wide>
      <p className="muted small p-eyebrow">Consent</p>
      <h1 style={{ marginTop: 4 }}>{study.name}</h1>

      <div className="p-prose" dangerouslySetInnerHTML={{ __html: html }} />

      {showVideoNotice && (
        <div className="p-notice">
          <strong>📹 This session is screen + microphone recorded.</strong> After you consent,
          you'll be asked to share <strong>this browser tab</strong> and allow your microphone.
          The recording is stored securely and viewable only by the research team.
        </div>
      )}

      <form onSubmit={onSubmit} style={{ marginTop: 28, display: "flex", gap: 10 }}>
        <button type="submit" className="btn primary" disabled={busy} style={{ padding: "10px 18px" }}>
          I consent — start →
        </button>
        <Link to="/" className="btn ghost">
          Cancel
        </Link>
      </form>
    </ParticipantCard>
  );
}
