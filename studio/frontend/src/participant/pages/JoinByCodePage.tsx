import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { apiPost, ApiError } from "../../lib/api";
import type { NextResponse } from "../../lib/types";
import { ParticipantCard } from "../components/ParticipantCard";


export function JoinByCodePage() {
  const { code } = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;
    let cancelled = false;
    (async () => {
      try {
        const qs = search.toString();
        const data = await apiPost<NextResponse>(`/api/join${qs ? `?${qs}` : ""}`, { code });
        if (cancelled) return;
        navigate(data.next ?? "/p/task", { replace: true });
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Something went wrong.");
      }
    })();
    return () => {
      cancelled = true;
    };
    
  }, [code]);

  if (error) {
    return (
      <ParticipantCard>
        <div className="alert error">{error}</div>
        <Link to="/" className="btn ghost">
          Back
        </Link>
      </ParticipantCard>
    );
  }

  return (
    <ParticipantCard centered>
      <p className="muted">Joining…</p>
    </ParticipantCard>
  );
}
