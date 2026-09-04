export function StatsBar({
  events,
  writes,
  bus,
  users,
  rate,
}: {
  events: number;
  writes: number;
  bus: number;
  users: number;
  rate: number;
}) {
  return (
    <div id="statsbar">
      <span className="stat-item">
        Events: <b>{events}</b>
      </span>
      <span className="stat-item">
        Writes: <b>{writes}</b>
      </span>
      <span className="stat-item">
        Bus: <b>{bus}</b>
      </span>
      <span className="stat-item">
        Users: <b>{users}</b>
      </span>
      <span id="event-rate">{rate} events/s</span>
    </div>
  );
}
