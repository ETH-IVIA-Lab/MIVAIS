import { useState } from "react";
import { ProactiveProvider } from "./context";
import { ProactiveApp } from "./ProactiveApp";
import { useStaticData } from "./useStaticData";

function fromUrl(key: string, fallback: string): string {
  return new URLSearchParams(location.search).get(key) || fallback;
}

export function App() {
  const [sessionId] = useState(() => fromUrl("session", Math.random().toString(36).slice(2, 10)));
  const [room] = useState(() => fromUrl("room", "default"));
  const [role] = useState(() => fromUrl("role", "analyst"));
  const staticData = useStaticData();

  if (!staticData) {
    return <div style={{ padding: 24, color: "#64748b", fontFamily: "system-ui" }}>Loading MC3 data…</div>;
  }

  return (
    <ProactiveProvider
      sessionId={sessionId}
      room={room}
      role={role}
      harnessStripKeys={["dataset", "hexgrid", "streets", "entities", "knowledge", "interaction_log"]}
    >
      <ProactiveApp staticData={staticData} />
    </ProactiveProvider>
  );
}
