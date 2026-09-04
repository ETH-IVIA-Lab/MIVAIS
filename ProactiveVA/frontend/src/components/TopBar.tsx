import { hashUserColor } from "mivais-va-client";
import { useProactive } from "../context";

const TOGGLES: { name: "onboarding" | "exploration" | "verification"; label: string }[] = [
  { name: "onboarding", label: "Onboarding On" },
  { name: "exploration", label: "Exploration On" },
  { name: "verification", label: "Verification On" },
];

export function TopBar({ onShowTutorial }: { onShowTutorial: () => void }) {
  const { connectionStatus, worldState, sendAction, connectedUsers, sessionId, myPermissions } = useProactive();
  const others = connectedUsers.filter((u) => u.session_id !== sessionId);

  return (
    <header className="topbar">
      <div className="left">
        <span id="conn-dot" data-state={connectionStatus} title={`WebSocket: ${connectionStatus}`} />
        <span className="role">
          {connectionStatus === "connected" ? `role: ${myPermissions.role || "analyst"}` : connectionStatus}
        </span>
        <span id="presence-bar">
          {others.map((u) => (
            <span
              key={u.session_id}
              className="user-pill"
              style={{ color: hashUserColor(u.session_id) }}
              title={`${u.session_id} · ${u.role || ""}`}
            >
              <span className="dot" />
              {u.session_id.slice(0, 4)}
            </span>
          ))}
        </span>
        <div className="freq" style={{ marginLeft: "auto" }}>
          <label>Help interval:</label>
          <span className="lim">1s</span>
          <input
            type="range"
            min={1}
            max={10}
            step={0.5}
            defaultValue={worldState.think_time_threshold_s ?? 3}
            title={`${worldState.think_time_threshold_s ?? 3}s`}
            onMouseUp={(e) => sendAction({ action: "set_threshold", seconds: parseFloat(e.currentTarget.value) })}
          />
          <span className="lim">10s</span>
        </div>
      </div>

      <div className="center">
        <span className="center-title">ProactiveVA</span>
        {TOGGLES.map(({ name, label }) => {
          const on = worldState[`${name}_enabled`] !== false;
          return (
            <label
              key={name}
              className={`switch${on ? " on" : ""}`}
              onClick={(e) => {
                e.preventDefault();
                sendAction({ action: "set_toggle", name, value: !on });
              }}
            >
              <span className="lbl-off">Off</span>
              <input type="checkbox" checked={on} readOnly />
              <span className="track" />
              <span className="lbl-on">{label}</span>
            </label>
          );
        })}
      </div>

      <div className="right-cap">
        <button className="help-btn" onClick={onShowTutorial}>
          ? Tutorial
        </button>
      </div>
    </header>
  );
}
