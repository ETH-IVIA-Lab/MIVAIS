
export const POSITIONS: Record<string, { x: number; y: number }> = {
  worldstate: { x: -150, y: 0 },
  messagebus: { x: 200, y: 0 },
  gateway: { x: 30, y: 230 },
  auditlog: { x: -350, y: 230 },
  agentregistry: { x: -200, y: 230 },
  svm_ranker: { x: -320, y: -230 },
  nl_command: { x: 160, y: -230 },
};

export const TOOLTIPS: Record<string, { title: string; desc: string }> = {
  worldstate: {
    title: "WorldState (Blackboard)",
    desc: "Shared memory for all agents. Agents read/write named keys. Triggers watch() callbacks on every write. Enforces permissions via PermGuard. Pattern: HEARSAY-II Blackboard (1980).",
  },
  messagebus: {
    title: "MessageBus (Pub/Sub)",
    desc: "Topic-based async message delivery. Publishers post BusMessages; subscribers receive them via async callbacks. Agents are fully decoupled — publisher does not know subscribers exist.",
  },
  gateway: {
    title: "Gateway (WebSocket Bridge)",
    desc: "Bridges WebSocket clients (users) to the infrastructure. Each connecting user is registered in AgentRegistry with role-based permissions. Mediates all client I/O.",
  },
  auditlog: {
    title: "AuditLog (Provenance)",
    desc: "Immutable append-only record of every WorldState write, bus message, and user action. Written to JSONL for full session replay and reproducibility evaluation.",
  },
  agentregistry: {
    title: "AgentRegistry + PermGuard",
    desc: "Stores AgentCapabilities per agent (can_read, can_write, bus topics). PermissionGuard is called on every WorldState write — returns True/False. Denied writes are also logged.",
  },
  svm_ranker: {
    title: "SVMRankingAgent",
    desc: "Reactive agent. Watches session_nudges and dataset, and subscribes to weights.compute_request/rank_all.request on the MessageBus. On trigger: fits SVM on user preference rankings, computes SAW weights, re-ranks all items, writes ranked_items + display_order.",
  },
};

export const STATIC_NODES: any[] = [
  { data: { id: "worldstate", label: "WorldState\nblackboard · 0 keys" }, classes: "n-worldstate", position: POSITIONS.worldstate },
  { data: { id: "messagebus", label: "MessageBus\npub/sub · 0 topics" }, classes: "n-bus", position: POSITIONS.messagebus },
  { data: { id: "gateway", label: "Gateway\nWebSocket · 0 users" }, classes: "n-gateway", position: POSITIONS.gateway },
  { data: { id: "auditlog", label: "AuditLog\n0 entries" }, classes: "n-audit", position: POSITIONS.auditlog },
  { data: { id: "agentregistry", label: "PermGuard\n0 agents registered" }, classes: "n-registry", position: POSITIONS.agentregistry },
  { data: { id: "svm_ranker", label: "SVMRanker\nreactive · watch" }, classes: "n-agent", position: POSITIONS.svm_ranker },
];

export const STATIC_EDGES: any[] = [
  { data: { id: "e-svm-ws", source: "svm_ranker", target: "worldstate", label: "_read/_write" }, classes: "e-write" },
  { data: { id: "e-bus-svm", source: "messagebus", target: "svm_ranker", label: "deliver" }, classes: "e-bus" },
  { data: { id: "e-bus-nl", source: "messagebus", target: "nl_command", label: "deliver" }, classes: "e-bus" },
  { data: { id: "e-gw-ws", source: "gateway", target: "worldstate", label: "watch_any()" }, classes: "e-infra" },
  { data: { id: "e-ws-gw", source: "worldstate", target: "gateway", label: "notify()" }, classes: "e-infra" },
  { data: { id: "e-gw-bus", source: "gateway", target: "messagebus", label: "subscribe()" }, classes: "e-infra" },
  { data: { id: "e-bus-gw", source: "messagebus", target: "gateway", label: "deliver()" }, classes: "e-infra" },
  { data: { id: "e-ws-audit", source: "worldstate", target: "auditlog", label: "record()" }, classes: "e-infra" },
  { data: { id: "e-ws-reg", source: "worldstate", target: "agentregistry", label: "can_write()?" }, classes: "e-infra" },
];

export const CY_STYLE: any[] = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      "text-valign": "center",
      "text-halign": "center",
      "font-family": "Inter, Segoe UI, system-ui",
      "font-size": 11,
      "font-weight": 600,
      color: "#1f2328",
      "text-wrap": "wrap",
      "text-max-width": 140,
      "border-width": 1.5,
      "border-color": "#d0d7de",
      "background-color": "#ffffff",
      shape: "round-rectangle",
      width: 160,
      height: 60,
      padding: 8,
      "transition-property": "border-color background-color border-width",
      "transition-duration": 200,
    },
  },
  { selector: ".n-worldstate", style: { "background-color": "#dce9ff", "border-color": "#0969da" } },
  { selector: ".n-bus", style: { "background-color": "#ede9fe", "border-color": "#8250df" } },
  { selector: ".n-gateway", style: { "background-color": "#fff3cd", "border-color": "#953800" } },
  { selector: ".n-audit", style: { "background-color": "#d9f0de", "border-color": "#1a7f37" } },
  { selector: ".n-registry", style: { "background-color": "#fde8cc", "border-color": "#953800" } },
  { selector: ".n-agent", style: { "background-color": "#e8e8ff", "border-color": "#6e40c9", width: 150, height: 56 } },
  {
    selector: ".n-user",
    style: { "background-color": "#d0e8ff", "border-color": "#0550ae", shape: "ellipse", width: 90, height: 56, "font-size": 10 },
  },
  { selector: ".flash-write", style: { "border-color": "#0969da", "border-width": 3, "background-color": "#b6d0f5" } },
  { selector: ".flash-bus", style: { "border-color": "#8250df", "border-width": 3, "background-color": "#d8c9f9" } },
  { selector: ".flash-user", style: { "border-color": "#0550ae", "border-width": 3, "background-color": "#b0d0f0" } },
  { selector: ".flash-deny", style: { "border-color": "#d1242f", "border-width": 3, "background-color": "#fdb8bb" } },
  { selector: ".flash-audit", style: { "border-color": "#1a7f37", "border-width": 3, "background-color": "#b0dfc0" } },
  { selector: ".node-selected", style: { "border-color": "#1f2328", "border-width": 3 } },
  {
    selector: "edge",
    style: {
      "line-color": "#d0d7de",
      "target-arrow-color": "#d0d7de",
      "target-arrow-shape": "triangle",
      "arrow-scale": 0.8,
      width: 1.5,
      "curve-style": "bezier",
      label: "data(label)",
      "font-size": 8,
      "font-family": "Inter, system-ui",
      color: "#57606a",
      "text-background-color": "#f6f8fa",
      "text-background-opacity": 1,
      "text-background-padding": "2px",
      "edge-text-rotation": "autorotate",
      opacity: 0.65,
    },
  },
  { selector: "edge.e-write", style: { "line-color": "#a8c8f0", "target-arrow-color": "#a8c8f0" } },
  { selector: "edge.e-bus", style: { "line-color": "#c8b8f0", "target-arrow-color": "#c8b8f0" } },
  { selector: "edge.e-user", style: { "line-color": "#90c4e8", "target-arrow-color": "#90c4e8", "line-style": "dashed" } },
  { selector: "edge.e-infra", style: { "line-color": "#c8d0d8", "target-arrow-color": "#c8d0d8", "line-style": "dashed" } },
  { selector: "edge.flash-edge", style: { "line-color": "#0969da", "target-arrow-color": "#0969da", width: 2.5, opacity: 1 } },
  {
    selector: ".packet",
    style: {
      width: 16,
      height: 16,
      shape: "ellipse",
      "background-color": "data(color)",
      "border-width": 0,
      label: "data(label)",
      "font-size": 9,
      color: "#fff",
      "text-halign": "right",
      "text-valign": "center",
      "text-margin-x": 8,
      "z-index": 9999,
      "overlay-opacity": 0,
    },
  },
];
