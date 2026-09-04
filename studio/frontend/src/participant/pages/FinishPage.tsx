import { useEffect, useState } from "react";
import { apiGet } from "../../lib/api";
import type { FinishResponse } from "../../lib/types";
import { ParticipantCard } from "../components/ParticipantCard";

function CompletionCode({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div style={{ marginTop: 16 }}>
      <p className="muted small" style={{ marginBottom: 6 }}>
        Your completion code
      </p>
      <div style={{ display: "flex", gap: 8, justifyContent: "center", alignItems: "center" }}>
        <code
          className="mono"
          style={{ fontSize: 22, letterSpacing: 2, padding: "8px 14px", background: "var(--panel-2, #f1f5f9)", borderRadius: 8 }}
        >
          {code}
        </code>
        <button
          type="button"
          className="btn ghost"
          onClick={() => {
            navigator.clipboard?.writeText(code).then(
              () => setCopied(true),
              () => setCopied(false),
            );
          }}
        >
          {copied ? "Copied ✓" : "Copy"}
        </button>
      </div>
    </div>
  );
}

export function FinishPage() {
  const [res, setRes] = useState<FinishResponse | null>(null);
  const [redirecting, setRedirecting] = useState(false);

  useEffect(() => {
    apiGet<FinishResponse>("/api/p/finish").then((data) => {
      setRes(data);
      let inIframe = false;
      try {
        inIframe = !!window.parent && window.parent !== window;
      } catch {
        inIframe = true; // cross-origin parent — definitely framed
      }
      if (inIframe) {
        try {
          window.parent.postMessage("studio:session_finished", "*");
        } catch {
          // no listener — ignore
        }
        return;
      }
      if (data.external_redirect) {
        setRedirecting(true);
        window.location.href = data.external_redirect;
      }
    });
  }, []);

  if (!res) {
    return (
      <ParticipantCard centered>
        <p className="muted">One moment…</p>
      </ParticipantCard>
    );
  }

  if (redirecting && res.external_redirect) {
    return (
      <ParticipantCard centered>
        <h1 style={{ marginTop: 0 }}>Thank you</h1>
        <p className="muted">Returning you to the study platform…</p>
        {res.completion_code && <CompletionCode code={res.completion_code} />}
        <p className="muted small" style={{ marginTop: 16 }}>
          Not redirected?{" "}
          <a href={res.external_redirect}>Click here to complete the study</a>.
        </p>
      </ParticipantCard>
    );
  }

  return (
    <ParticipantCard centered>
      <div className="p-icon-circle success">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 6L9 17l-5-5" />
        </svg>
      </div>
      <h1 style={{ marginTop: 0 }}>Thank you</h1>
      <p>Your responses have been recorded.</p>
      {res.completion_code && <CompletionCode code={res.completion_code} />}
      <p className="muted small" style={{ marginTop: 12 }}>
        You may now close this tab.
      </p>
    </ParticipantCard>
  );
}
