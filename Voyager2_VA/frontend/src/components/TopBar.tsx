import type { ConnectionStatus } from "mivais-va-client";

export function TopBar({
  connectionStatus,
  usersBar,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  onHelp,
  onBookmarks,
}: {
  connectionStatus: ConnectionStatus;
  usersBar: React.ReactNode;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onHelp: () => void;
  onBookmarks: () => void;
}) {
  const connected = connectionStatus === "connected";
  return (
    <div className="topbar">
      <span className="topbar-title">
        Voyager 2<span className="topbar-subtitle">(MIVAIS)</span>
      </span>
      {usersBar}
      <div className="topbar-spacer" />
      <div className="topbar-status">
        <span className={`status-dot${connected ? " connected" : ""}`} />
        <span>{connected ? "Connected" : connectionStatus === "reconnecting" ? "Disconnected" : "Connecting…"}</span>
      </div>
      <button className="topbar-btn" disabled={!canUndo} title="Undo" onClick={onUndo}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M3 10h13a4 4 0 0 1 0 8H7" />
          <path d="M3 10l4-4" />
          <path d="M3 10l4 4" />
        </svg>
        Undo
      </button>
      <button className="topbar-btn" disabled={!canRedo} title="Redo" onClick={onRedo}>
        Redo
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M21 10H8a4 4 0 0 0 0 8h9" />
          <path d="M21 10l-4-4" />
          <path d="M21 10l-4 4" />
        </svg>
      </button>
      <button className="topbar-btn" title="How to use" onClick={onHelp}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <circle cx="12" cy="12" r="10" />
          <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
        Help
      </button>
      <button className="topbar-btn" onClick={onBookmarks}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
        </svg>
        Bookmarks
      </button>
    </div>
  );
}
