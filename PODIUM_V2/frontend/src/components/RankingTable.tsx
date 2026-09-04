import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CursorMap } from "mivais-va-client";
import { hashUserColor } from "mivais-va-client";
import { getRowName } from "../types";
import type { DatasetRow, RankedItem } from "../types";
import { deriveRowCursorState } from "./CursorOverlay";

export interface RankingTableProps {
  numericCols: string[];
  rankedItems: RankedItem[];
  displayOrder: string[];
  dataset: DatasetRow[];
  draggable?: boolean;
  onReorder?: (newOrder: string[]) => void;
  onDragStateChange?: (dragging: string | null, dragOver: string | null) => void;
  onRowHover?: (name: string | null) => void;
  cursors?: CursorMap;
  ownSessionId?: string;
  
  highlightRowName?: string | null;
  highlightNonce?: number;
}

export function buildItems(rankedItems: RankedItem[], displayOrder: string[]): RankedItem[] {
  if (!displayOrder.length) return rankedItems;
  const byName = new Map(rankedItems.map((r) => [getRowName(r), r]));
  const ordered = displayOrder.map((n) => byName.get(n)).filter((x): x is RankedItem => Boolean(x));
  const covered = new Set(displayOrder);
  rankedItems.forEach((r) => {
    if (!covered.has(getRowName(r))) ordered.push(r);
  });
  return ordered;
}

export function RankingTable({
  numericCols,
  rankedItems,
  displayOrder,
  dataset,
  draggable = false,
  onReorder,
  onDragStateChange,
  onRowHover,
  cursors = {},
  ownSessionId = "",
  highlightRowName,
  highlightNonce,
}: RankingTableProps) {
  
  const [optimisticOrder, setOptimisticOrder] = useState<string[] | null>(null);
  const preDropSig = useRef<string>("");
  const sig = (names: string[]) => JSON.stringify(names);
  useEffect(() => {
    if (optimisticOrder && sig(displayOrder) !== preDropSig.current) {
      setOptimisticOrder(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [displayOrder]);

  const items = buildItems(rankedItems, optimisticOrder ?? displayOrder);
  const tbodyRef = useRef<HTMLTableSectionElement>(null);
  const prevPositions = useRef<Map<string, number>>(new Map());
  const dragSrc = useRef<string | null>(null);
  const dragThrottle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [dragOverName, setDragOverName] = useState<string | null>(null);
  const [draggingName, setDraggingName] = useState<string | null>(null);

  const clearDragThrottle = () => {
    if (dragThrottle.current) {
      clearTimeout(dragThrottle.current);
      dragThrottle.current = null;
    }
  };

  
  const prevOrderSig = useRef<string>("");
  const orderSig = items.map(getRowName).join(" ");
  useLayoutEffect(() => {
    const tbody = tbodyRef.current;
    if (!tbody) return;
    const rows = Array.from(tbody.querySelectorAll<HTMLTableRowElement>("tr[data-name]"));
    const orderChanged = prevOrderSig.current !== "" && prevOrderSig.current !== orderSig;
    if (orderChanged) {
      rows.forEach((row) => {
        const name = row.dataset.name!;
        const oldTop = prevPositions.current.get(name);
        const newTop = row.offsetTop;
        if (oldTop !== undefined && Math.abs(oldTop - newTop) > 1) {
          const delta = oldTop - newTop;
          row.style.transition = "none";
          row.style.transform = `translateY(${delta}px)`;
          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              row.style.transition = "transform .55s cubic-bezier(0.34,1.35,0.64,1)";
              row.style.transform = "translateY(0)";
              row.classList.add("row-flash");
              setTimeout(() => row.classList.remove("row-flash"), 1100);
            });
          });
        }
      });
    }
    const next = new Map<string, number>();
    rows.forEach((row) => next.set(row.dataset.name!, row.offsetTop));
    prevPositions.current = next;
    prevOrderSig.current = orderSig;
  });

  useEffect(() => {
    if (!highlightRowName) return;
    const tbody = tbodyRef.current;
    const row = tbody?.querySelector<HTMLTableRowElement>(`tr[data-name="${CSS.escape(highlightRowName)}"]`);
    if (!row) return;
    row.classList.remove("row-highlighted");
    void row.offsetWidth;
    row.classList.add("row-highlighted");
    const t = setTimeout(() => row.classList.remove("row-highlighted"), 2600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlightRowName, highlightNonce]);

  const colMin: Record<string, number> = {};
  const colMax: Record<string, number> = {};
  numericCols.forEach((c) => {
    const vals = dataset.map((r) => Number(r[c])).filter((v) => !Number.isNaN(v));
    colMin[c] = vals.length ? Math.min(...vals) : 0;
    colMax[c] = vals.length ? Math.max(...vals) : 0;
  });
  const nameToData = new Map(dataset.map((r) => [getRowName(r), r]));
  const maxScore = Math.max(...items.map((r) => r.score ?? 0), 0.001);
  const { hover: rowHover, dragging: rowDragging, dragOver: rowDragOver } = deriveRowCursorState(cursors, ownSessionId);

  const handleDrop = (targetName: string) => {
    if (!dragSrc.current || dragSrc.current === targetName) return;
    const names = items.map(getRowName);
    const srcIdx = names.indexOf(dragSrc.current);
    const tgtIdx = names.indexOf(targetName);
    if (srcIdx === -1 || tgtIdx === -1) return;
    const newOrder = [...names];
    newOrder.splice(srcIdx, 1);
    const insertAt = newOrder.indexOf(targetName) + (srcIdx < tgtIdx ? 1 : 0);
    newOrder.splice(insertAt, 0, dragSrc.current);
    preDropSig.current = sig(displayOrder); 
    setOptimisticOrder(newOrder); 
    onReorder?.(newOrder);
  };

  return (
    <table className={`rank-table${draggable ? "" : " no-drag"}`}>
      <thead id="rank-thead">
        <tr>
          <th>#</th>
          <th>Name</th>
          {numericCols.map((c) => (
            <th key={c} className="th-feat">
              {c}
            </th>
          ))}
          <th>Score</th>
          <th />
          <th>⠿</th>
          <th />
        </tr>
      </thead>
      <tbody ref={tbodyRef}>
        {items.map((item, i) => {
          const name = getRowName(item);
          const score = item.score ?? 0;
          const pct = ((score / maxScore) * 100).toFixed(1);
          const row = nameToData.get(name) ?? {};
          const rowClasses = [
            dragOverName === name ? "drag-over" : "",
            draggingName === name ? "dragging" : "",
            !draggingName && rowDragging[name]?.length ? "remote-dragging" : "",
            !draggingName && rowDragOver[name]?.length ? "remote-drag-over" : "",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <tr
              key={name}
              data-name={name}
              className={rowClasses || undefined}
              draggable={draggable}
              onDragStart={() => {
                dragSrc.current = name;
                setDraggingName(name);
                onDragStateChange?.(name, null);
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOverName(name);
                if (dragThrottle.current) return;
                dragThrottle.current = setTimeout(() => {
                  onDragStateChange?.(dragSrc.current, name);
                  dragThrottle.current = null;
                }, 50);
              }}
              onDrop={(e) => {
                e.preventDefault();
                clearDragThrottle(); 
                handleDrop(name);
                setDragOverName(null);
              }}
              onDragEnd={() => {
                clearDragThrottle();
                dragSrc.current = null;
                setDraggingName(null);
                setDragOverName(null);
                onDragStateChange?.(null, null);
              }}
              onMouseEnter={() => onRowHover?.(name)}
              onMouseLeave={() => onRowHover?.(null)}
            >
              <td>
                <span className={`rank-num${i < 3 ? " top" : ""}`}>{i + 1}</span>
              </td>
              <td>{name}</td>
              {numericCols.map((c) => {
                const val = row[c];
                if (val === undefined || val === null) return <td key={c} className="td-feat">—</td>;
                const n = Number(val);
                const hi = !Number.isNaN(n) && colMax[c] !== colMin[c] && n >= colMin[c] + (colMax[c] - colMin[c]) * 0.75;
                return (
                  <td key={c} className={`td-feat${hi ? " feat-hi" : ""}`}>
                    {Number.isNaN(n) ? String(val) : n % 1 === 0 ? n : n.toFixed(1)}
                  </td>
                );
              })}
              <td>
                {score > 0 && (
                  <div className="score-bar-wrap">
                    <div className="score-bar" style={{ width: `${pct}%` }} />
                  </div>
                )}
              </td>
              <td className="td-score">{score > 0 ? score.toFixed(3) : ""}</td>
              <td className="td-grip">{draggable ? "⠿" : ""}</td>
              <td className="td-cursors">
                {(rowHover[name] ?? []).slice(0, 4).map((sid) => (
                  <span key={sid} className="cursor-badge" style={{ background: hashUserColor(sid) }} title={sid}>
                    {sid.slice(0, 2).toUpperCase()}
                  </span>
                ))}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
