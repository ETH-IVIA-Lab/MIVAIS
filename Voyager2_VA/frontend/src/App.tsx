import { useState } from "react";
import { VoyagerProvider } from "./context";
import { VoyagerApp } from "./VoyagerApp";

function getRoomFromUrl(): string {
  return new URLSearchParams(location.search).get("room") || "default";
}

function getSessionFromUrl(): string {
  return new URLSearchParams(location.search).get("session") || Math.random().toString(36).slice(2, 10);
}

function getDatasetFromUrl(): string {
  return new URLSearchParams(location.search).get("dataset") || "";
}

export function App() {
  const [sessionId] = useState(getSessionFromUrl);
  const [room] = useState(getRoomFromUrl);
  // Dataset request travels on the WS URL; the server resolves it when the
  // room is CREATED (later joiners share the room's dataset regardless).
  const [dataset] = useState(getDatasetFromUrl);

  return (
    <VoyagerProvider
      sessionId={sessionId}
      room={room}
      role="analyst"
      wsQuery={dataset ? { dataset } : undefined}
    >
      <VoyagerApp />
    </VoyagerProvider>
  );
}
