import { useEffect, useState, type CSSProperties, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { apiGet, apiPost } from "../../lib/api";
import type { NextResponse, RoleOption, RolePickerResponse } from "../../lib/types";
import { ParticipantCard } from "../components/ParticipantCard";
import { useRoleState } from "../hooks/useRoleState";

export function RolePickerPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<RolePickerResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [full, setFull] = useState(false);
  const [busy, setBusy] = useState(false);
  const { roles: liveRoles, redirect } = useRoleState(!!data?.roles);

  useEffect(() => {
    apiGet<RolePickerResponse>("/api/p/role").then((res) => {
      if (res.next) {
        navigate(res.next, { replace: true });
        return;
      }
      setData(res);
    });
  }, [navigate]);

  useEffect(() => {
    if (redirect) navigate(redirect, { replace: true });
  }, [redirect, navigate]);

  const roles: RoleOption[] = liveRoles ?? data?.roles ?? [];

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!selected) return;
    setBusy(true);
    setFull(false);
    try {
      const res = await apiPost<NextResponse>("/api/p/role", { role: selected });
      if (res.error === "full") {
        setFull(true);
        return;
      }
      navigate(res.next ?? "/p/task", { replace: true });
    } finally {
      setBusy(false);
    }
  }

  if (!data) {
    return (
      <ParticipantCard wide>
        <p className="muted">Loading…</p>
      </ParticipantCard>
    );
  }

  return (
    <ParticipantCard wide>
      <p className="muted small p-eyebrow">Role selection</p>
      <h1 style={{ marginTop: 4 }}>Pick your role</h1>
      <p className="muted">
        Your researcher set up this study with multiple roles. Choose the one you've been asked to
        play.
      </p>

      {full && (
        <div className="alert error" style={{ marginTop: 16 }}>
          That role was just filled by someone else. Pick another.
        </div>
      )}

      <form onSubmit={onSubmit} className="role-grid">
        {roles.map((r) => {
          const isFull = r.available === 0;
          const style = r.color ? ({ "--role-color": r.color } as CSSProperties) : undefined;
          return (
            <label
              key={r.id}
              className={`role-card ${isFull ? "disabled" : ""} ${selected === r.id ? "selected" : ""}`}
              style={style}
            >
              <input
                type="radio"
                name="role"
                value={r.id}
                disabled={isFull && selected !== r.id}
                checked={selected === r.id}
                onChange={() => setSelected(r.id)}
                required
              />
              <div className="role-card-inner">
                <h3>{r.name || r.id}</h3>
                {r.description && <p className="muted small">{r.description}</p>}
                <div className="muted small" style={{ marginTop: 10 }}>
                  {r.capacity ? (
                    isFull ? (
                      <span className="chip warn">full</span>
                    ) : (
                      `${r.available} of ${r.capacity} slot${r.capacity === 1 ? "" : "s"} left`
                    )
                  ) : (
                    "unlimited slots"
                  )}
                </div>
              </div>
            </label>
          );
        })}
        <button type="submit" className="btn primary role-confirm" disabled={busy || !selected}>
          Confirm role
        </button>
      </form>
    </ParticipantCard>
  );
}
