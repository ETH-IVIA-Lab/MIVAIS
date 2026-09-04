import { useMemo, useState } from "react";
import { AGENT_NEUTRAL, prettyAgent } from "./classify";
import type { ClassifiedEvent } from "./types";

function fmtT(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(2)}s`;
}

export function AgentMessages({
  classified,
  currentT,
  onJump,
}: {
  classified: ClassifiedEvent[];
  currentT: number;
  onJump: (t_ms: number) => void;
}) {
  const messages = useMemo(
    () => classified.filter((e) => e.type === "bus_message"),
    [classified],
  );
  const [open, setOpen] = useState<Set<number>>(new Set());

  function toggle(i: number) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  return (
    <aside className="replay-events card">
      <header className="replay-section-head">
        <h2>Agent messages</h2>
        <span className="muted small">{messages.length || "none"}</span>
      </header>
      <ol className="agent-msg-list">
        {messages.length === 0 && (
          <li className="muted small" style={{ padding: "6px 8px" }}>
            No agent-to-agent messages were recorded for this session.
          </li>
        )}
        {messages.map((m, i) => {
          const meta = m.meta || {};
          const sender = (meta.sender as string) || "agent";
          const topic = (meta.topic as string) || "";
          const isChat = topic === "chat.message";
          const text = meta.text;
          const payload = meta.payload_preview;
          const color = AGENT_NEUTRAL;
          const isPast = m.t_ms <= currentT;
          const expanded = open.has(i);
          return (
            <li key={i} className="agent-msg" style={{ opacity: isPast ? 1 : 0.55 }}>
              <div className="agent-msg-head" onClick={() => onJump(m.t_ms)} title={`jump to ${fmtT(m.t_ms)}`}>
                <span className="agent-msg-dot" style={{ background: color }} />
                <span className="agent-msg-sender" style={{ color }}>
                  {prettyAgent(sender)}
                </span>
                <span className="agent-msg-topic mono small">{topic}</span>
                <span className="agent-msg-time mono small muted">{fmtT(m.t_ms)}</span>
              </div>
              {isChat && text ? (
                <div className="agent-msg-text">{text}</div>
              ) : payload ? (
                <>
                  <button type="button" className="agent-msg-toggle" onClick={() => toggle(i)}>
                    {expanded ? "▾ payload" : "▸ payload"}
                  </button>
                  {expanded && <pre className="agent-msg-payload">{payload}</pre>}
                </>
              ) : null}
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
