import { useMemo, useRef, useState } from "react";
import { useProactive } from "../context";
import { filteredMessages, fmtClock } from "../helpers";
import type { Mc3Message } from "../types";

export function MessagesView({ dataset }: { dataset: Mc3Message[] }) {
  const { worldState, sendAction } = useProactive();
  const [kw, setKw] = useState("");
  const hoverT = useRef<ReturnType<typeof setTimeout> | null>(null);

  const filtered = useMemo(
    () => filteredMessages(dataset, worldState),
    [
      dataset,
      worldState.selected_hex,
      worldState.selected_entity,
      worldState.keyword_filter,
      worldState.time_range,
    ],
  );

  const tags: string[] = [];
  if (worldState.selected_hex) tags.push(`hex:${worldState.selected_hex}`);
  if (worldState.selected_entity) tags.push(`entity:${worldState.selected_entity}`);
  if ((worldState.keyword_filter || []).length) tags.push(`kw:${(worldState.keyword_filter || []).join(",")}`);
  const tr = worldState.time_range;
  if (tr && tr.start != null && tr.end != null) tags.push(`time:${fmtClock(tr.start)}-${fmtClock(tr.end)}`);

  const highlighted = new Set(worldState.highlighted_message_ids || []);
  const staged = new Set(worldState.staged_evidence || []);
  const slice = filtered.slice(0, 200);

  const addKeyword = () => {
    const v = kw.trim();
    if (!v) return;
    const cur = (worldState.keyword_filter || []).slice();
    if (!cur.includes(v)) sendAction({ action: "set_keyword_filter", keywords: [...cur, v] });
    setKw("");
  };

  const hover = (id: string) => {
    if (hoverT.current) clearTimeout(hoverT.current);
    hoverT.current = setTimeout(() => sendAction({ action: "hover_message", message_id: id }), 80);
  };

  return (
    <>
      <header className="subhead">
        Messages — {filtered.length} / {dataset.length}
        {tags.length ? " · " + tags.join(" · ") : ""}
      </header>
      <div className="keyword-bar">
        {(worldState.keyword_filter || []).map((k) => (
          <span
            key={k}
            className="keyword-chip"
            onClick={() =>
              sendAction({
                action: "set_keyword_filter",
                keywords: (worldState.keyword_filter || []).filter((x) => x !== k),
              })
            }
          >
            {k} x
          </span>
        ))}
        <input
          className="keyword-input"
          placeholder="add keyword + Enter"
          value={kw}
          onChange={(e) => setKw(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addKeyword()}
        />
      </div>
      <div className="body">
        <div id="messages-list">
          {slice.map((m) => {
            const cls = ["message-row", `s-${m.sentiment}`];
            if (highlighted.has(m.id)) cls.push("highlighted");
            if (staged.has(m.id)) cls.push("staged");
            return (
              <div
                key={m.id}
                className={cls.join(" ")}
                data-id={m.id}
                onMouseEnter={() => hover(m.id)}
                onClick={() => sendAction({ action: "select_message", message_id: m.id })}
              >
                <div className="meta">
                  <span className={`badge ${m.type === "ccdata" ? "cc" : "mb"}`}>
                    {m.type === "ccdata" ? "CC" : "MB"}
                  </span>
                  {(m.timestamp || "").slice(11, 19)} {m.author || "?"} {m.location ? "· " + m.location : ""}
                </div>
                <div className="body">
                  {m.message || ""}{" "}
                  {(m.entities || []).map((e) => (
                    <span key={e} style={{ color: "#6366f1" }}>
                      #{e}{" "}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
          {!slice.length && <div className="empty-hint">No messages match the current filters.</div>}
        </div>
      </div>
    </>
  );
}
