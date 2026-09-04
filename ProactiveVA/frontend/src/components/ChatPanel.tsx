import { useEffect, useRef, useState } from "react";
import { useProactive } from "../context";
import { markupHtml } from "../helpers";
import type { Suggestion, TraceStep } from "../types";

const MAX_PENDING_VISIBLE = 3;

function toLabel(to?: string): string {
  if (!to || to === "broadcast" || to === "all") return "";
  if (to === "acting_agent") return " → Assistant";
  if (to.startsWith("user:")) return " → " + to.slice(5, 9);
  return " → " + to;
}

function SuggestionCard({ s }: { s: Suggestion }) {
  const { sendAction } = useProactive();
  const status = s.status || "pending";
  const cls = [
    "suggestion",
    status === "completed" || status === "acting" ? "completed" : "",
    status === "rejected" || status === "dismissed" ? "rejected" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={cls}>
      <div className="meta">
        {s.category} · {s.subcategory || ""} {s.pattern ? "· " + s.pattern : ""}
      </div>
      <div className="text" dangerouslySetInnerHTML={markupHtml(s.suggestion_text || "")} />
      {status === "pending" ? (
        <div className="actions">
          <button className="accept" title="Run this suggestion" onClick={() => sendAction({ action: "accept_suggestion", id: s.id })}>
            Try it
          </button>
          <button className="reject" title="Dismiss" onClick={() => sendAction({ action: "reject_suggestion", id: s.id })}>
            Not now
          </button>
        </div>
      ) : (
        <div className="meta" style={{ marginTop: 4 }}>
          status: {status}
        </div>
      )}
    </div>
  );
}

function TraceBlock({ steps }: { steps: TraceStep[] }) {
  
  const [collapsed, setCollapsed] = useState(true);
  if (!steps.length) return null;
  return (
    <div className={`trace${collapsed ? " collapsed" : ""}`}>
      <div className="toggle" onClick={() => setCollapsed(!collapsed)} title={collapsed ? "Show the assistant's reasoning" : "Hide details"}>
        <span>
          Assistant reasoning · {steps.length} step{steps.length === 1 ? "" : "s"}
        </span>
        <span className="caret">{collapsed ? "▼" : "▲"}</span>
      </div>
      <div className="steps">
        {steps.slice(-12).map((s, i) => (
          <div className="step" key={i}>
            {s.thought && <div className="thought">{s.thought}</div>}
            {s.action && (
              <div className="action">
                {s.action}({JSON.stringify(s.action_args || {}).slice(0, 120)})
              </div>
            )}
            {s.observation != null && <div className="observation">{String(s.observation).slice(0, 200)}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ChatPanel() {
  const { worldState, chatHistory, sendChat, connectedUsers, sessionId } = useProactive();
  const [text, setText] = useState("");
  const [to, setTo] = useState("broadcast");
  const [blink, setBlink] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  const suggestions = worldState.pending_suggestions || [];
  const trace = worldState.agent_trace || [];
  const agentStatus = worldState.agent_status?.state || "idle";

  
  const pendingIds = suggestions.filter((s) => (s.status || "pending") === "pending").map((s) => s.id);
  const hiddenPending = new Set(pendingIds.slice(0, Math.max(0, pendingIds.length - MAX_PENDING_VISIBLE)));
  const visibleSuggestions = suggestions.filter((s) => !hiddenPending.has(s.id));

  // Auto-scroll on new content + blink the mission strip on new suggestions.
  const lastCount = useRef(0);
  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    if (suggestions.length > lastCount.current) {
      setBlink(true);
      const t = setTimeout(() => setBlink(false), 1200);
      lastCount.current = suggestions.length;
      return () => clearTimeout(t);
    }
    lastCount.current = suggestions.length;
  }, [chatHistory.length, suggestions.length, trace.length]);

  const submit = () => {
    const v = text.trim();
    if (!v) return;
    sendChat(v, to);
    setText("");
  };

  const others = connectedUsers.filter((u) => u.session_id !== sessionId);

  return (
    <section className="panel" id="chat">
      <div className={`mission${blink ? " blink" : ""}`}>
        <b>Your mission:</b> identify as many public-safety events from the evening of 2014-01-23 in
        Abila as possible. For each one, record <b>time</b>, <b>location</b>, and{" "}
        <b>people involved</b> as a Note (right panel). The assistant watches you and offers help —
        accept its suggestions or ask it directly with <code>@assistant …</code>.
      </div>
      <div className={`agent-status${agentStatus === "idle" ? " idle" : ""}`}>
        {agentStatus === "thinking" ? "Assistant thinking…" : agentStatus === "acting" ? "Assistant acting…" : "Assistant idle"}
      </div>
      <div className="body" ref={bodyRef}>
        <div className="msg system">
          <div className="who">ProactiveVA</div>
          <div className="text">
            Welcome. I watch how you explore the data and offer help when you seem stuck.{"\n"}
            Try filtering messages, brushing the timeline, or selecting a hexagon — suggestions will
            appear here.
          </div>
        </div>
        {chatHistory.map((m, i) => {
          const fromAgent = m.from_role === "agent" || (m.from || "").includes("agent");
          const isPrivate = !!m.to && m.to !== "broadcast" && m.to !== "all";
          const isSelf = (m.from || "") === `user:${sessionId}`;
          const recipient = toLabel(m.to);
          return (
            <div key={i} className={`msg ${fromAgent ? "agent" : "user"}${isPrivate ? " private" : ""}`}>
              <div className="who">
                {isSelf ? "You" : m.from_display || m.from || "?"}
                {recipient && <span style={{ color: "#94a3b8", fontWeight: 400 }}>{recipient}</span>}
              </div>
              <div className="text" dangerouslySetInnerHTML={markupHtml(m.text || "")} />
            </div>
          );
        })}
        {visibleSuggestions.map((s) => (
          <SuggestionCard key={s.id} s={s} />
        ))}
        <TraceBlock steps={trace} />
      </div>
      <div className="footer">
        <select id="chat-to" title="Who to send to" value={to} onChange={(e) => setTo(e.target.value)}>
          <option value="broadcast">To: Everyone</option>
          <option value="acting_agent">To: Assistant</option>
          {others.map((u) => (
            <option key={u.session_id} value={`user:${u.session_id}`}>
              To: {u.session_id.slice(0, 4)} ({u.role || ""})
            </option>
          ))}
        </select>
        <input
          id="chat-input"
          placeholder="Type a message — or @assistant …"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        <button id="chat-send" title="Send" onClick={submit}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" fill="currentColor" />
          </svg>
        </button>
      </div>
    </section>
  );
}
