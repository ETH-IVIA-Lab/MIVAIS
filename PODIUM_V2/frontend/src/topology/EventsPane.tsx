export interface LogEntry {
  id: number;
  badge: string;
  badgeCls: string;
  actor: string;
  actorColor: string;
  detail: string;
  key?: string;
  time: string;
}

export function EventsPane({ entries }: { entries: LogEntry[] }) {
  return (
    <div id="events-pane">
      <div id="events-header">LIVE EVENT STREAM</div>
      <div id="log-body">
        {entries.map((e) => (
          <div className="log-entry" key={e.id}>
            <div className="log-meta">
              <span className={`log-badge ${e.badgeCls}`}>{e.badge}</span>
              <span className="log-actor" style={{ color: e.actorColor }}>
                {e.actor}
              </span>
              <span className="log-time">{e.time}</span>
            </div>
            <div className="log-detail">
              {e.key && <span className="log-key">{e.key}</span>}
              {e.key && " — "}
              {e.detail}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
