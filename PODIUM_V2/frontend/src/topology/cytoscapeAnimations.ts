import type { Core } from "cytoscape";

let packetSeq = 0;

export function firePacket(cy: Core, srcId: string, tgtId: string, color: string, label = "", duration = 900) {
  const src = cy.getElementById(srcId);
  const tgt = cy.getElementById(tgtId);
  if (!src.length || !tgt.length) return;

  const id = `pkt-${packetSeq++}`;
  cy.add({ group: "nodes", data: { id, color, label }, position: { ...src.position() }, classes: "packet" });
  cy.getElementById(id).animate(
    { position: { ...tgt.position() } },
    {
      duration,
      easing: "ease-in-out-cubic",
      complete: () => {
        const el = cy.getElementById(id);
        if (el.length) el.remove();
      },
    },
  );

  const edges = cy.edges().filter(
    (e) => (e.data("source") === srcId && e.data("target") === tgtId) || (e.data("source") === tgtId && e.data("target") === srcId),
  );
  if (edges.length) {
    edges.addClass("flash-edge");
    setTimeout(() => edges.removeClass("flash-edge"), duration);
  }
}

export function flashNode(cy: Core, id: string, cls: string, ms = 600) {
  const el = cy.getElementById(id);
  if (!el.length) return;
  el.addClass(cls);
  setTimeout(() => el.removeClass(cls), ms);
}

export function animateWritePipeline(cy: Core, actorNode: string, accepted: boolean, key: string) {
  flashNode(cy, actorNode, accepted ? "flash-write" : "flash-deny", 500);
  firePacket(cy, actorNode, "agentregistry", accepted ? "#3fb950" : "#f85149", "check?", 600);

  setTimeout(() => {
    if (accepted) {
      flashNode(cy, "agentregistry", "flash-audit", 500);
      firePacket(cy, "agentregistry", "worldstate", "#58a6ff", key ? key.slice(0, 14) : "write", 700);
    } else {
      flashNode(cy, "agentregistry", "flash-deny", 600);
      flashNode(cy, actorNode, "flash-deny", 600);
    }
  }, 650);

  if (!accepted) return;

  setTimeout(() => {
    flashNode(cy, "worldstate", "flash-write", 500);
    firePacket(cy, "worldstate", "auditlog", "#3fb950", "record()", 600);
  }, 1400);

  setTimeout(() => {
    firePacket(cy, "worldstate", "gateway", "#58a6ff", "notify()", 600);
  }, 1550);

  setTimeout(() => {
    flashNode(cy, "gateway", "flash-write", 500);
    cy.nodes(".n-user").forEach((uNode) => {
      firePacket(cy, "gateway", uNode.data("id"), "#39d3f2", "push", 500);
    });
  }, 2100);
}

export function animateBusPipeline(cy: Core, publisherNode: string, topic: string) {
  flashNode(cy, publisherNode, "flash-bus", 600);
  firePacket(cy, publisherNode, "messagebus", "#a78bfa", topic ? topic.split(".").pop() ?? "" : "msg", 700);

  setTimeout(() => {
    flashNode(cy, "messagebus", "flash-bus", 500);
    firePacket(cy, "messagebus", "gateway", "#a78bfa", "deliver", 600);
  }, 750);

  setTimeout(() => {
    flashNode(cy, "gateway", "flash-bus", 500);
    cy.nodes(".n-user").forEach((uNode) => {
      firePacket(cy, "gateway", uNode.data("id"), "#39d3f2", "bus", 600);
    });
  }, 1400);
}

export function ensureUserNode(cy: Core, agentId: string, role: string, userCount: number) {
  if (cy.getElementById(agentId).length) return;
  cy.add({
    group: "nodes",
    data: { id: agentId, label: `${agentId.replace("user:", "").slice(0, 6)}\n(${role || "user"})`, role },
    position: { x: 450, y: -120 + userCount * 90 },
    classes: "n-user",
  });
  cy.add({
    group: "edges",
    data: { id: `e-${agentId}`, source: agentId, target: "gateway", label: "WebSocket" },
    classes: "e-user",
  });
}

export function syncUserNodes(cy: Core, connected: Array<{ session_id: string; role: string }>) {
  const wanted = new Set(connected.map((u) => `user:${u.session_id}`));
  cy.nodes(".n-user").forEach((n) => {
    if (!wanted.has(n.id())) {
      cy.remove(cy.getElementById(`e-${n.id()}`));
      n.remove();
    }
  });
  connected.forEach((u, i) => ensureUserNode(cy, `user:${u.session_id}`, u.role, i));
}

export function updateNodeLabels(
  cy: Core,
  stats: { worldStateKeys: number; writeCount: number; auditCount: number; userCount: number; busCount: number },
) {
  cy.getElementById("worldstate").data("label", `WorldState\n${stats.worldStateKeys} keys · ${stats.writeCount} writes`);
  cy.getElementById("auditlog").data("label", `AuditLog\n${stats.auditCount} entries`);
  cy.getElementById("gateway").data("label", `Gateway\nWebSocket · ${stats.userCount} users`);
  cy.getElementById("agentregistry").data("label", `PermGuard\n${3 + stats.userCount} agents registered`);
  cy.getElementById("messagebus").data("label", `MessageBus\npub/sub · ${stats.busCount} msgs`);
}
