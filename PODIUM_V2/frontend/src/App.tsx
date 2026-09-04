import { useState } from "react";
import { PodiumProvider } from "./context";
import { Dashboard } from "./dashboard/Dashboard";

function getRoomFromUrl(): string {
  return new URLSearchParams(location.search).get("room") || "default";
}

export function App() {
  const [sessionId] = useState(() => crypto.randomUUID());
  const [room] = useState(getRoomFromUrl);

  return (
    <PodiumProvider sessionId={sessionId} room={room} role="analyst">
      <Dashboard />
    </PodiumProvider>
  );
}
