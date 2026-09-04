import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useCursorTracking } from "mivais-va-client/react";
import { useVoyager } from "./context";
import { TYPE_ABBR } from "./types";
import type { EncodingEntry, ShelfEntry, ViewSpec } from "./types";
import { useEncodingState } from "./hooks/useEncodingState";
import { BookmarksModal } from "./components/BookmarksModal";
import type { InsightPopoverPayload } from "./components/ChatMessage";
import { ChatPanel } from "./components/ChatPanel";
import { ConnectedUsersBar } from "./components/ConnectedUsersBar";
import { CursorOverlay } from "./components/CursorOverlay";
import { EncodingPanel } from "./components/EncodingPanel";
import { FieldList } from "./components/FieldList";
import { FilterBar } from "./components/FilterBar";
import type { DragField } from "./components/FieldList";
import { FocusView } from "./components/FocusView";
import { InsightPopover } from "./components/InsightPopover";
import { RelatedSection } from "./components/RelatedSection";
import { TopBar } from "./components/TopBar";
import { TutorialOverlay } from "./components/TutorialOverlay";
import { WildcardGallery } from "./components/WildcardGallery";
import { parseCsv } from "./csv";
import type { FilterSpec } from "./types";

const TUTORIAL_SEEN_KEY = "voyager2_tutorial_seen";

function switchDataset(name: string) {
  const params = new URLSearchParams(location.search);
  const baseRoom = (params.get("room") || "default").split("~")[0];
  params.set("dataset", name);
  params.set("room", baseRoom === "default" && !params.get("room") ? "default" : `${baseRoom}~${name}`);
  location.search = params.toString();
}

export function VoyagerApp() {
  const { worldState, connectionStatus, cursors, connectedUsers, onlineAgents, chatHistory, sessionId, sendAction, sendCursor, sendChat, canPublish } =
    useVoyager();
  useCursorTracking(sendCursor);

  const sendUpdateSpec = useCallback(
    (spec: { mark: string; encodings: EncodingEntry[] }) => {
      sendAction({ action: "update_spec", spec });
    },
    [sendAction],
  );
  const encoding = useEncodingState(sendUpdateSpec);

  useEffect(() => {
    encoding.syncFromServerSpec(worldState.current_spec);
  }, [worldState.current_spec]);

  const [bookmarksOpen, setBookmarksOpen] = useState(false);
  const [tutorialOpen, setTutorialOpen] = useState(false);
  const [serverDatasets, setServerDatasets] = useState<string[]>([]);
  const csvInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch("/datasets")
      .then((r) => r.json())
      .then((d) => setServerDatasets(d.datasets ?? []))
      .catch(() => {});
  }, []);

  const filters = useMemo(() => worldState.filters ?? [], [worldState.filters]);
  const setFilters = useCallback((next: FilterSpec[]) => sendAction({ action: "set_filters", filters: next }), [sendAction]);

  const onCsvPicked = useCallback(
    async (file: File) => {
      const rows = parseCsv(await file.text());
      if (!rows.length) return;
      sendAction({ action: "load_dataset", name: file.name.replace(/\.csv$/i, ""), dataset: rows });
    },
    [sendAction],
  );
  const [popover, setPopover] = useState<InsightPopoverPayload | null>(null);
  const popoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (typeof localStorage === "undefined" || localStorage.getItem(TUTORIAL_SEEN_KEY)) return;
    const t = setTimeout(() => setTutorialOpen(true), 500);
    return () => clearTimeout(t);
  }, []);

  const dismissTutorial = useCallback(() => {
    setTutorialOpen(false);
    localStorage.setItem(TUTORIAL_SEEN_KEY, "1");
  }, []);

  const showPopover = useCallback((insight: InsightPopoverPayload) => {
    if (popoverTimer.current) clearTimeout(popoverTimer.current);
    setPopover(insight);
    popoverTimer.current = setTimeout(() => setPopover(null), 12000);
  }, []);

  const dismissPopover = useCallback(() => {
    if (popoverTimer.current) clearTimeout(popoverTimer.current);
    popoverTimer.current = null;
    setPopover(null);
  }, []);

  const handleDrop = useCallback(
    (channel: string, dragField: DragField) => {
      const entry: ShelfEntry = {
        field: dragField.field,
        type: dragField.type,
        aggregate: dragField.isCount ? "count" : "none",
        bin: false,
        timeUnit: "",
      };
      encoding.dropField(channel, entry);
    },
    [encoding],
  );

  const handleRemove = useCallback(
    (target: { channel: string } | { anyIdx: number }) => {
      if ("channel" in target) encoding.removeChannel(target.channel);
      else encoding.removeAnyField(target.anyIdx);
    },
    [encoding],
  );

  const handleSpecify = useCallback((view: ViewSpec) => sendAction({ action: "specify_view", view }), [sendAction]);
  const bookmarks = worldState.bookmarks ?? [];
  const bookmarkKeys = useMemo(() => new Set(bookmarks.map((b) => JSON.stringify(b.view))), [bookmarks]);
  const isBookmarked = useCallback(
    (view: ViewSpec | null | undefined) => !!view && bookmarkKeys.has(JSON.stringify(view)),
    [bookmarkKeys],
  );
  const handleBookmark = useCallback(
    (view: ViewSpec) => {
      const key = JSON.stringify(view);
      const idx = bookmarks.findIndex((b) => JSON.stringify(b.view) === key);
      if (idx >= 0) sendAction({ action: "remove_bookmark", index: idx });
      else sendAction({ action: "add_bookmark", view, note: "" });
    },
    [bookmarks, sendAction],
  );

  const handlePopoverAction = useCallback(
    (suggestion: NonNullable<InsightPopoverPayload["suggestion"]>) => {
      if (suggestion.add_field) {
        const abbr = TYPE_ABBR[suggestion.add_field.type as keyof typeof TYPE_ABBR] || "N";
        encoding.autoAssignField(suggestion.add_field.field, suggestion.add_field.type, abbr);
      } else if (suggestion.spec || suggestion.filter_nulls) {
        sendAction({ action: "select_insight_action", suggestion });
      }
      dismissPopover();
    },
    [encoding, dismissPopover, sendAction],
  );

  const dataset = worldState.dataset ?? [];
  const fields = worldState.data_fields ?? [];
  const nonCountFieldCount = fields.filter((f) => !f.is_count).length;
  const datasetName = worldState.dataset_name ? `${worldState.dataset_name} · ` : "";
  const datasetLabel = fields.length
    ? dataset.length
      ? `${datasetName}${dataset.length} rows, ${nonCountFieldCount} fields`
      : `${datasetName}${nonCountFieldCount} fields`
    : "No dataset loaded";

  const toOptions = [
    { value: "broadcast", label: "Everyone" },
    ...onlineAgents.map((a) => ({ value: a.id, label: `${a.id} (agent)` })),
    ...connectedUsers
      .filter((u) => u.session_id !== sessionId)
      .map((u) => ({ value: `user:${u.session_id}`, label: `${u.session_id.slice(0, 6)} (${u.role || "user"})` })),
  ];

  return (
    <>
      <TopBar
        connectionStatus={connectionStatus}
        usersBar={<ConnectedUsersBar users={connectedUsers} ownSessionId={sessionId} />}
        canUndo={encoding.canUndo}
        canRedo={encoding.canRedo}
        onUndo={encoding.doUndo}
        onRedo={encoding.doRedo}
        onHelp={() => setTutorialOpen(true)}
        onBookmarks={() => setBookmarksOpen(true)}
      />

      <div className="main">
        <div className="panel-left">
          <div className="panel-left-header">
            <h2>Data</h2>
            <div className="dataset-name">{datasetLabel}</div>
            <select
              className="dataset-select"
              title="Switch dataset (fresh room) or open a local CSV (this room only, nothing uploaded)"
              value={serverDatasets.includes(worldState.dataset_name ?? "") ? worldState.dataset_name : "__local__"}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "__csv__") csvInputRef.current?.click();
                else if (v !== "__local__" && v !== worldState.dataset_name) switchDataset(v);
              }}
            >
              {!serverDatasets.includes(worldState.dataset_name ?? "") && (
                <option value="__local__">{worldState.dataset_name || "custom"} (local)</option>
              )}
              {serverDatasets.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
              <option value="__csv__">Open CSV…</option>
            </select>
            <input
              ref={csvInputRef}
              type="file"
              accept=".csv"
              style={{ display: "none" }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onCsvPicked(f);
                e.target.value = "";
              }}
            />
          </div>
          <FieldList fields={fields} onAutoAssign={(field, type, abbr) => encoding.autoAssignField(field, type, abbr)} />
        </div>

        <div className="panel-center">
          <EncodingPanel
            mark={encoding.mark}
            shelves={encoding.shelves}
            anyFields={encoding.anyFields}
            onMarkChange={encoding.setMark}
            onDrop={handleDrop}
            onChange={encoding.updateEntry}
            onRemove={handleRemove}
          />
          <FilterBar fields={fields} dataset={dataset} filters={filters} onChange={setFilters} />
          <div className="focus-area">
            <FocusView
              view={worldState.focus_view ?? null}
              dataset={dataset}
              filters={filters}
              bookmarked={isBookmarked(worldState.focus_view)}
              onBookmark={() => worldState.focus_view && handleBookmark(worldState.focus_view)}
              popover={popover && <InsightPopover insight={popover} onDismiss={dismissPopover} onAction={handlePopoverAction} />}
            />
            <WildcardGallery
              results={worldState.wildcard_results ?? []}
              dataset={dataset}
              filters={filters}
              onSpecify={handleSpecify}
              onBookmark={handleBookmark}
              isBookmarked={isBookmarked}
            />
          </div>
        </div>

        <div className="panel-right">
          <RelatedSection title="Summaries" specs={worldState.related_summaries ?? []} dataset={dataset} filters={filters} onSpecify={handleSpecify} onBookmark={handleBookmark} isBookmarked={isBookmarked} />
          <RelatedSection title="Field Suggestions" specs={worldState.field_suggestions ?? []} dataset={dataset} filters={filters} onSpecify={handleSpecify} onBookmark={handleBookmark} isBookmarked={isBookmarked} />
          <RelatedSection title="Alternative Encodings" specs={worldState.alt_encodings ?? []} dataset={dataset} filters={filters} onSpecify={handleSpecify} onBookmark={handleBookmark} isBookmarked={isBookmarked} />
        </div>
      </div>

      <CursorOverlay cursors={cursors} ownSessionId={sessionId} />

      <ChatPanel
        messages={chatHistory}
        ownSessionId={sessionId}
        toOptions={toOptions}
        canSend={canPublish("chat.message")}
        onSend={sendChat}
        onInsightPopover={showPopover}
      />

      <TutorialOverlay open={tutorialOpen} onDismiss={dismissTutorial} />

      <BookmarksModal
        open={bookmarksOpen}
        bookmarks={worldState.bookmarks ?? []}
        dataset={dataset}
        onClose={() => setBookmarksOpen(false)}
        onUpdateNote={(index, note) => sendAction({ action: "update_bookmark_note", index, note })}
        onRemove={(index) => sendAction({ action: "remove_bookmark", index })}
      />
    </>
  );
}
