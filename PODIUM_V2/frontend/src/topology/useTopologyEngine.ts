import { useCallback, useEffect, useRef, useState } from "react";
import type { Core } from "cytoscape";
import { usePodium } from "../context";
import {
  animateBusPipeline,
  animateWritePipeline,
  ensureUserNode,
  firePacket,
  flashNode,
  syncUserNodes,
  updateNodeLabels,
} from "./cytoscapeAnimations";
import { actorColor } from "./utils";
import type { LogEntry } from "./EventsPane";
import type { TooltipState } from "./Tooltip";

const MAX_LOG = 80;

export function useTopologyEngine(cy: Core | null) {
  const { worldState, auditLog, subscribeNewAuditEntries, connectedUsers, connectionStatus } = usePodium();
  const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const [stats, setStats] = useState({ events: 0, writes: 0, bus: 0, users: 0 });
  const [rate, setRate] = useState(0);
  const rateRef = useRef(0);
  const logSeq = useRef(0);
  const prevUserIds = useRef<Set<string>>(new Set());
  const statsRef = useRef(stats);
  statsRef.current = stats;

  const addLog = useCallback((badge: string, badgeCls: string, actor: string, detail: string, key?: string) => {
    setLogEntries((prev) => {
      const entry: LogEntry = {
        id: logSeq.current++,
        badge,
        badgeCls,
        actor,
        actorColor: actorColor(actor),
        detail,
        key,
        time: new Date().toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }),
      };
      const next = [entry, ...prev];
      return next.length > MAX_LOG ? next.slice(0, MAX_LOG) : next;
    });
  }, []);

  const incEvent = useCallback((kind?: "write" | "bus") => {
    rateRef.current++;
    setStats((s) => ({ ...s, events: s.events + 1, writes: kind === "write" ? s.writes + 1 : s.writes, bus: kind === "bus" ? s.bus + 1 : s.bus }));
  }, []);

  useEffect(() => {
    const t = setInterval(() => {
      setRate(rateRef.current);
      rateRef.current = 0;
    }, 1000);
    return () => clearInterval(t);
  }, []);

  // New/removed user presence: sync graph nodes + log CONNECT + users stat.
  useEffect(() => {
    if (!cy) return;
    connectedUsers.forEach((u, i) => {
      const id = `user:${u.session_id}`;
      if (!prevUserIds.current.has(id)) {
        ensureUserNode(cy, id, u.role, i);
        flashNode(cy, id, "flash-user", 900);
        addLog("CONNECT", "lb-connect", id, `connected as ${u.role || "user"}`);
      }
    });
    syncUserNodes(cy, connectedUsers);
    prevUserIds.current = new Set(connectedUsers.map((u) => `user:${u.session_id}`));
    setStats((s) => ({ ...s, users: connectedUsers.length }));
  }, [cy, connectedUsers, addLog]);

  // Periodic node label refresh (live counts).
  useEffect(() => {
    if (!cy) return;
    const t = setInterval(() => {
      updateNodeLabels(cy, {
        worldStateKeys: Object.keys(worldState).filter((k) => k !== "dataset").length,
        writeCount: statsRef.current.writes,
        auditCount: auditLog.length,
        userCount: connectedUsers.length,
        busCount: statsRef.current.bus,
      });
    }, 2000);
    return () => clearInterval(t);
  }, [cy, worldState, auditLog.length, connectedUsers.length]);

  // Audit-log diff drives packet animations + the live event log.
  useEffect(() => {
    return subscribeNewAuditEntries((entries) => {
      entries.forEach((entry) => {
        const actor = entry.actor || "?";
        const key = entry.key || "";
        const evType = entry.event_type || "";
        const accepted = entry.accepted !== false;

        let actorNode = "gateway";
        if (cy?.getElementById(actor).length) actorNode = actor;
        else if (actor.startsWith("user:")) actorNode = actor;

        if (evType === "state_write" || evType === "write") {
          incEvent("write");
          if (cy) animateWritePipeline(cy, actorNode, accepted, key);
          addLog(accepted ? "WRITE" : "DENY", accepted ? "lb-write" : "lb-deny", actor, accepted ? `→ WorldState[${key}]` : "blocked by PermGuard", key);
        } else if (evType === "bus_message") {
          incEvent("bus");
          const topic = key.replace(/^bus:/, "");
          if (cy) animateBusPipeline(cy, actorNode, topic);
          addLog("BUS", "lb-bus", actor, topic, topic);
        } else if (evType === "cursor_move") {
          if (cy) flashNode(cy, actorNode, "flash-user", 300);
        } else if (evType === "user_input") {
          incEvent("write");
          if (cy) {
            firePacket(cy, actorNode, "gateway", "#39d3f2", key ? key.slice(0, 12) : "input", 600);
            setTimeout(() => {
              flashNode(cy, "gateway", "flash-user", 400);
              firePacket(cy, "gateway", "worldstate", "#39d3f2", key ? key.slice(0, 12) : "fwd", 700);
            }, 600);
            setTimeout(() => flashNode(cy, "worldstate", "flash-user", 400), 1250);
          }
          addLog("USER", "lb-user", actor, key || evType, key);
        }
      });
    });
  }, [cy, subscribeNewAuditEntries, addLog, incEvent]);

  return {
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
  };
}
