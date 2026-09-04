import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiGet, apiPost } from "../../lib/api";
import type { LobbyPageResponse, LobbyParticipant } from "../../lib/types";
import { ParticipantCard } from "../components/ParticipantCard";
import { useLobbyState } from "../hooks/useLobbyState";

const isReady = (status: string) => status === "ready" || status === "in_session";

export function LobbyPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<LobbyPageResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const { state: liveState, released } = useLobbyState(!!data?.participants);

  useEffect(() => {
    apiGet<LobbyPageResponse>("/api/p/lobby").then((res) => {
      if (res.next) {
        navigate(res.next, { replace: true });
        return;
      }
      setData(res);
    });
  }, [navigate]);

  useEffect(() => {
    if (released) navigate("/p/task", { replace: true });
  }, [released, navigate]);

  if (!data) {
    return (
      <ParticipantCard wide>
        <p className="muted">Loading…</p>
      </ParticipantCard>
    );
  }

  const { study, participant, required = 0 } = data;
  const participants: LobbyParticipant[] =
    liveState?.participants ??
    (data.participants ?? []).map((p) => ({
      anon_id: p.anon_id,
      role: p.role,
      status: p.status,
      is_self: p.id === participant?.id,
    }));
  const readyCount = liveState?.ready_count ?? participants.filter((p) => isReady(p.status)).length;
  const selfReady = participants.find((p) => p.is_self) ? isReady(participants.find((p) => p.is_self)!.status) : false;

  async function onReady() {
    setBusy(true);
    try {
      await apiPost("/api/p/lobby/ready");
    } finally {
      setBusy(false);
    }
  }

  return (
    <ParticipantCard wide>
      <p className="muted small p-eyebrow">Multiplayer lobby</p>
      <h1 style={{ marginTop: 4 }}>Waiting for the rest of the group</h1>
      <p className="muted">
        {study?.name} runs as a {required}-person session. Once everyone in your cohort clicks{" "}
        <strong>I'm ready</strong>, the study starts at the same moment for all of you.
      </p>

      <div className="lobby-presence">
        {participants.map((p, i) => (
          <div
            key={`${p.anon_id}-${i}`}
            className={`presence-card ${isReady(p.status) ? "is-ready" : ""} ${p.is_self ? "is-self" : ""}`}
          >
            <div className="presence-anon">
              {p.anon_id}
              {p.is_self && <span className="muted small"> (you)</span>}
            </div>
            {p.role && <div className="presence-role">{p.role}</div>}
            <div className="presence-status">
              {isReady(p.status) ? <span className="chip ok">ready</span> : <span className="chip">waiting</span>}
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 18 }}>
        <span className="muted">
          {readyCount} of {required} ready
        </span>
        {!selfReady ? (
          <button type="button" className="btn primary" style={{ padding: "10px 18px" }} disabled={busy} onClick={onReady}>
            I'm ready
          </button>
        ) : (
          <span className="chip ok">you're ready</span>
        )}
      </div>
    </ParticipantCard>
  );
}
