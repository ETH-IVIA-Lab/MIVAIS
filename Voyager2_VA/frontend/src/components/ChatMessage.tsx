import { useEffect } from "react";
import { hashUserColor, parseMarkedText, stripLevelPrefix } from "mivais-va-client";
import type { ChatPayload } from "mivais-va-client";
import { VOYAGER_USER_PALETTE } from "./ConnectedUsersBar";

export interface InsightPopoverPayload {
  level?: "warning" | "ok" | "info";
  title?: string;
  text?: string;
  suggestion?: { label?: string; spec?: unknown; add_field?: { field: string; type: string }; filter_nulls?: { field: string } };
}

function MessageText({ text }: { text: string }) {
  const { text: clean } = stripLevelPrefix(text);
  const segments = parseMarkedText(clean);
  return (
    <span className="cm-text">
      {segments.map((seg, i) => {
        if (seg.type === "mark") return <mark key={i} className="hl-pulse">{seg.value}</mark>;
        if (seg.type === "bold") return <strong key={i}>{seg.value}</strong>;
        return <span key={i}>{seg.value}</span>;
      })}
    </span>
  );
}

export function ChatMessage({
  payload,
  ownSessionId,
  onInsightPopover,
}: {
  payload: ChatPayload & { _popover?: InsightPopoverPayload };
  ownSessionId: string;
  onInsightPopover?: (popover: InsightPopoverPayload) => void;
}) {
  const from = payload.from_display || payload.from || "";
  const text = payload.text || "";
  const ts = payload.timestamp
    ? new Date(typeof payload.timestamp === "number" ? payload.timestamp * 1000 : payload.timestamp).toLocaleTimeString()
    : "";
  const isAgent = /^(insight_|recommendation_)/.test(payload.from || "");
  const isWarning = text.startsWith("[!]");

  useEffect(() => {
    if (isAgent && payload._popover) onInsightPopover?.(payload._popover);
    
  }, []);

  if (isAgent) {
    return (
      <div className={`chat-msg insight${isWarning ? " warning" : ""}`}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
          <span className="cm-icon">{isWarning ? "!" : "i"}</span>
          <div style={{ flex: 1 }}>
            <span className="cm-from" style={{ color: isWarning ? "var(--amber)" : "var(--purple)" }}>
              {from}
            </span>
            <span className="cm-time">{ts}</span>
            <MessageText text={text} />
          </div>
        </div>
      </div>
    );
  }

  const sid = (payload.from || "").replace("user:", "");
  const color = sid && sid !== payload.from ? hashUserColor(sid, VOYAGER_USER_PALETTE) : "var(--text)";
  return (
    <div className="chat-msg user-msg">
      <span className="cm-from" style={{ color }}>
        {from}
      </span>
      <span className="cm-time">{ts}</span>
      <MessageText text={text} />
    </div>
  );
}
