import { parseMarkedText } from "mivais-va-client";
import type { InsightPopoverPayload } from "./ChatMessage";

export function InsightPopover({
  insight,
  onDismiss,
  onAction,
}: {
  insight: InsightPopoverPayload;
  onDismiss: () => void;
  onAction: (suggestion: NonNullable<InsightPopoverPayload["suggestion"]>) => void;
}) {
  const isWarning = insight.level === "warning";
  const segments = parseMarkedText(insight.text || "");

  return (
    <div className={`insight-popover${isWarning ? " warning" : ""}`}>
      <button className="pop-dismiss" title="Dismiss" onClick={onDismiss}>
        ×
      </button>
      <div className="pop-header">
        <span className="pop-icon">{isWarning ? "!" : "i"}</span>
        <span className="pop-title">{insight.title || "Insight"}</span>
      </div>
      <div className="pop-body">
        {segments.map((seg, i) =>
          seg.type === "mark" ? (
            <mark key={i} className="hl-pulse">
              {seg.value}
            </mark>
          ) : seg.type === "bold" ? (
            <strong key={i}>{seg.value}</strong>
          ) : (
            <span key={i}>{seg.value}</span>
          ),
        )}
      </div>
      {insight.suggestion && (
        <div className="pop-action" onClick={() => onAction(insight.suggestion!)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path d="M5 12h14M12 5l7 7-7 7" />
          </svg>
          {insight.suggestion.label || "Try this"}
        </div>
      )}
    </div>
  );
}
