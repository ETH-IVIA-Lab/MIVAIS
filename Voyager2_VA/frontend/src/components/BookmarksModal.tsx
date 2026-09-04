import { useEffect, useRef, useState } from "react";
import type { Bookmark } from "../types";
import { VegaChart } from "./VegaChart";

function BookmarkItem({
  bookmark,
  index,
  dataset,
  onUpdateNote,
  onRemove,
}: {
  bookmark: Bookmark;
  index: number;
  dataset: unknown[];
  onUpdateNote: (index: number, note: string) => void;
  onRemove: (index: number) => void;
}) {
  const [note, setNote] = useState(bookmark.note || "");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setNote(bookmark.note || "");
  }, [bookmark.note]);

  useEffect(() => () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
  }, []);

  return (
    <div className="bookmark-item">
      <VegaChart spec={bookmark.view} dataset={dataset} width={300} height={200} renderer="canvas" lazy compact className="bookmark-thumb" />
      <div className="bookmark-meta">
        {bookmark.by && <div className="by-label">by {bookmark.by.replace(/^user:/, "").slice(0, 8)}</div>}
        <textarea
          value={note}
          placeholder="Add a note..."
          onChange={(e) => {
            const value = e.target.value;
            setNote(value);
            if (debounceRef.current) clearTimeout(debounceRef.current);
            debounceRef.current = setTimeout(() => onUpdateNote(index, value), 500);
          }}
        />
        <button type="button" className="bookmark-delete" onClick={() => onRemove(index)}>
          Remove
        </button>
      </div>
    </div>
  );
}

export function BookmarksModal({
  open,
  bookmarks,
  dataset,
  onClose,
  onUpdateNote,
  onRemove,
}: {
  open: boolean;
  bookmarks: Bookmark[];
  dataset: unknown[];
  onClose: () => void;
  onUpdateNote: (index: number, note: string) => void;
  onRemove: (index: number) => void;
}) {
  return (
    <div
      className={`bookmark-overlay${open ? " open" : ""}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bookmark-panel">
        <div className="bookmark-panel-header">
          <h2>Bookmarks</h2>
          <button className="bookmark-close" onClick={onClose}>
            ×
          </button>
        </div>
        {bookmarks.length === 0 ? (
          <div className="bookmark-empty">No bookmarks yet. Star a view to save it here.</div>
        ) : (
          bookmarks.map((bk, i) => (
            <BookmarkItem key={i} bookmark={bk} index={i} dataset={dataset} onUpdateNote={onUpdateNote} onRemove={onRemove} />
          ))
        )}
      </div>
    </div>
  );
}
