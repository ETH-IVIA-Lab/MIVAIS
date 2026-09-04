import { useCallback, useEffect, useState } from "react";
import type { Core } from "cytoscape";
import { PodiumProvider } from "../context";
import { EventsPane } from "./EventsPane";
import { InspectorPane } from "./InspectorPane";
import { StatsBar } from "./StatsBar";
import { TopBar } from "./TopBar";
import { Tooltip } from "./Tooltip";
import { TopologyGraph } from "./TopologyGraph";
import { useTopologyEngine } from "./useTopologyEngine";

function TopologyView() {
  const [cy, setCy] = useState<Core | null>(null);
  const [tab, setTab] = useState<"events" | "inspector">("events");
  const {
    worldState,
    auditLog,
    connectedUsers,
    connectionStatus,
    logEntries,
    selectedNodeId,
    setSelectedNodeId,
    tooltip,
    setTooltip,
    stats,
    rate,
  } = useTopologyEngine(cy);

  const selectNode = useCallback(
    (nodeId: string) => {
      if (selectedNodeId) cy?.getElementById(selectedNodeId).removeClass("node-selected");
      setSelectedNodeId(nodeId);
      cy?.getElementById(nodeId).addClass("node-selected");
      setTooltip(null);
      setTab("inspector");
    },
    [cy, selectedNodeId, setSelectedNodeId, setTooltip],
  );

  const deselect = useCallback(() => {
    if (selectedNodeId) cy?.getElementById(selectedNodeId).removeClass("node-selected");
    setSelectedNodeId(null);
    setTab("events");
  }, [cy, selectedNodeId, setSelectedNodeId]);

  const resetView = useCallback(() => {
    cy?.animate({ fit: { eles: cy.nodes(), padding: 80 } }, { duration: 400, easing: "ease-out" });
  }, [cy]);

  const [, setZoomToggle] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "r" || e.key === "R") resetView();
      if (e.key === "f" || e.key === "F") {
        setZoomToggle((z) => {
          const next = !z;
          if (cy) {
            if (next) cy.animate({ zoom: 1, center: { eles: cy.nodes() } }, { duration: 350 });
            else cy.animate({ fit: { eles: cy.nodes(), padding: 80 } }, { duration: 350 });
          }
          return next;
        });
      }
      if (e.key === "Escape") deselect();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [cy, resetView, deselect, setZoomToggle]);

  return (
    <>
      <TopBar status={connectionStatus} onReset={resetView} />
      <TopologyGraph onReady={setCy} onNodeTap={selectNode} onBackgroundTap={deselect} onTooltip={setTooltip} />
      <div id="right-panel">
        <div id="panel-tabs">
          <button className={`tab-btn${tab === "events" ? " active" : ""}`} onClick={() => setTab("events")}>
            Events
          </button>
          <button className={`tab-btn${tab === "inspector" ? " active" : ""}`} onClick={() => setTab("inspector")}>
            Inspector
          </button>
        </div>
        {tab === "events" ? (
          <EventsPane entries={logEntries} />
        ) : (
          <InspectorPane
            active
            selectedNodeId={selectedNodeId}
            onBack={deselect}
            worldState={worldState}
            auditLog={auditLog}
            connectedUsers={connectedUsers}
            busCount={stats.bus}
          />
        )}
      </div>
      <Tooltip tooltip={tooltip} />
      <StatsBar events={stats.events} writes={stats.writes} bus={stats.bus} users={stats.users} rate={rate} />
      <div id="kb-hint">R = reset view &nbsp; F = fit/zoom &nbsp; ESC = deselect &nbsp; dbl-click = zoom node</div>
    </>
  );
}

export function TopologyApp() {
  const [sessionId] = useState(() => crypto.randomUUID());
  return (
    <PodiumProvider sessionId={sessionId} role="observer">
      <TopologyView />
    </PodiumProvider>
  );
}
