import { useEffect, useRef, useState } from "react";
import { hashUserColor, parseMarkedText } from "mivais-va-client";
import type { ChatPayload } from "mivais-va-client";

export interface ChatToOption {
  value: string;
  label: string;
}

function ChatMessageText({ text, onHighlightRow }: { text: string; onHighlightRow?: (name: string) => void }) {
  const segments = parseMarkedText(text);
  const marks = segments.filter((s) => s.type === "mark").map((s) => s.value);
  useEffect(() => {
    marks.forEach((name) => onHighlightRow?.(name));
  }, []);
  return (
    <span className="cm-text">
      {segments.map((seg, i) => {
        if (seg.type === "mark") return <mark key={i} className="cm-hl">{seg.value}</mark>;
        if (seg.type === "bold") return <strong key={i}>{seg.value}</strong>;
        return <span key={i}>{seg.value}</span>;
      })}
    </span>
  );
}

export function ChatPanel({
  messages,
  ownSessionId,
  toOptions,
  canSend,
  onSend,
  onHighlightRow,
}: {
  messages: ChatPayload[];
  ownSessionId: string;
  toOptions: ChatToOption[];
  canSend: boolean;
  onSend: (text: string, to: string) => void;
  onHighlightRow?: (name: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(true);
  const [unread, setUnread] = useState(0);
  const [input, setInput] = useState("");
  const [to, setTo] = useState("broadcast");
  const messagesRef = useRef<HTMLDivElement>(null);
  const prevCount = useRef(messages.length);

  useEffect(() => {
    if (messages.length > prevCount.current) {
      if (collapsed) setUnread((u) => u + (messages.length - prevCount.current));
      messagesRef.current?.scrollTo({ top: messagesRef.current.scrollHeight });
    }
    prevCount.current = messages.length;
  }, [messages, collapsed]);

  const toggle = () => {
    setCollapsed((c) => {
      if (c) setUnread(0);
      return !c;
    });
  };

  const send = () => {
    if (!input.trim()) return;
    onSend(input, to);
    setInput("");
  };

  return (
    <div id="chat-panel" className={collapsed ? "collapsed" : undefined}>
      <div id="chat-header" onClick={toggle}>
        <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor" style={{ verticalAlign: -2, marginRight: 4 }}>
          <path d="M2 2h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H5l-3 3V3a1 1 0 0 1 1-1z" />
        </svg>
        Chat
        {unread > 0 && <span className="chat-unread">{unread}</span>}
        <span id="chat-toggle-icon">{collapsed ? "▲" : "▼"}</span>
      </div>
      <div id="chat-body">
        <div id="chat-messages" ref={messagesRef}>
          {messages.map((m, i) => {
            const isMine = m.from === `user:${ownSessionId}` || m.from === ownSessionId;
            const color = isMine ? "var(--accent)" : hashUserColor(m.from.startsWith("user:") ? m.from.slice(5) : m.from);
            const ts = m.timestamp ? new Date(typeof m.timestamp === "number" ? m.timestamp * 1000 : m.timestamp).toLocaleTimeString() : "";
            const toLabel = m.to && m.to !== "broadcast" ? m.to.replace("user:", "").slice(0, 6) : null;
            return (
              <div className="chat-msg" key={i}>
                <div className="cm-meta">
                  <span className="cm-from" style={{ color }}>
                    {m.from_display ?? m.from.slice(0, 6)}
                  </span>
                  {toLabel && (
                    <span className="cm-to">
                      {" "}
                      → <span style={{ opacity: 0.7 }}>{toLabel}</span>
                    </span>
                  )}
                  <span style={{ fontSize: 9, color: "var(--muted)" }}>{ts}</span>
                </div>
                <ChatMessageText text={m.text} onHighlightRow={onHighlightRow} />
              </div>
            );
          })}
        </div>
        <div id="chat-input-row">
          <select id="chat-to" value={to} onChange={(e) => setTo(e.target.value)}>
            {toOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <input
            id="chat-input"
            type="text"
            placeholder="Message… use [mark:text] to highlight a row"
            value={input}
            disabled={!canSend}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
          />
          <button id="chat-send" type="button" disabled={!canSend} onClick={send}>
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
