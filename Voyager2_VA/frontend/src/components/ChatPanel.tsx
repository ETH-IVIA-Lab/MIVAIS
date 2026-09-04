import { useEffect, useRef, useState } from "react";
import type { ChatPayload } from "mivais-va-client";
import { ChatMessage } from "./ChatMessage";
import type { InsightPopoverPayload } from "./ChatMessage";

export interface ChatToOption {
  value: string;
  label: string;
}

export function ChatPanel({
  messages,
  ownSessionId,
  toOptions,
  canSend,
  onSend,
  onInsightPopover,
}: {
  messages: ChatPayload[];
  ownSessionId: string;
  toOptions: ChatToOption[];
  canSend: boolean;
  onSend: (text: string, to: string) => void;
  onInsightPopover?: (popover: InsightPopoverPayload) => void;
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

  const toggle = () =>
    setCollapsed((c) => {
      if (c) setUnread(0);
      return !c;
    });

  const send = () => {
    if (!input.trim()) return;
    onSend(input, to);
    setInput("");
  };

  return (
    <div id="chatPanel" className={`chat-panel${collapsed ? " collapsed" : ""}`}>
      <div id="chatHeader" className="chat-header" onClick={toggle}>
        <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor" style={{ verticalAlign: -2, marginRight: 4 }}>
          <path d="M2 2h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H5l-3 3V3a1 1 0 0 1 1-1z" />
        </svg>
        Chat
        {unread > 0 && <span className="chat-unread">{unread}</span>}
        <span style={{ marginLeft: "auto", fontSize: 10 }}>{collapsed ? "▲" : "▼"}</span>
      </div>
      <div className="chat-body">
        <div className="chat-messages" ref={messagesRef}>
          {messages.map((m, i) => (
            <ChatMessage key={i} payload={m} ownSessionId={ownSessionId} onInsightPopover={onInsightPopover} />
          ))}
        </div>
        <div className="chat-input-row">
          <select value={to} onChange={(e) => setTo(e.target.value)} title="Send to">
            {toOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <input
            type="text"
            placeholder="Message..."
            value={input}
            disabled={!canSend}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
          />
          <button type="button" disabled={!canSend} onClick={send}>
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
