import type { ReactNode } from "react";

function markerId(color?: string): string {
  switch (color) {
    case "#58a6ff":
      return "arr-blue";
    case "#3fb950":
      return "arr-green";
    case "#f85149":
      return "arr-red";
    case "#a78bfa":
      return "arr-purple";
    case "#39d3f2":
      return "arr-cyan";
    case "#f59e0b":
      return "arr-amber";
    case "#818cf8":
      return "arr-indigo";
    default:
      return "arr-gray";
  }
}

export function Diagram({ children, height, caption }: { children: ReactNode; height: number; caption?: string }) {
  return (
    <div className="ins-diagram">
      <div>
        <svg width={264} height={height} viewBox={`0 0 264 ${height}`} xmlns="http://www.w3.org/2000/svg" style={{ fontFamily: "Inter,system-ui,sans-serif" }}>
          {children}
        </svg>
        {caption && <div className="ins-diagram-caption">{caption}</div>}
      </div>
    </div>
  );
}

export function Box({ x, y, w, h, fill, stroke, label, fontSize = 9 }: { x: number; y: number; w: number; h: number; fill: string; stroke: string; label: string; fontSize?: number }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={5} fill={fill} stroke={stroke} strokeWidth={1.5} />
      <text x={x + w / 2} y={y + h / 2 + fontSize / 3} textAnchor="middle" fill={stroke} fontSize={fontSize} fontWeight={600}>
        {label}
      </text>
    </g>
  );
}

export function Arrow({ x1, y1, x2, y2, color = "#8b949e", label, lx, ly }: { x1: number; y1: number; x2: number; y2: number; color?: string; label?: string; lx?: number; ly?: number }) {
  return (
    <g>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={1.5} markerEnd={`url(#${markerId(color)})`} />
      {label && lx !== undefined && (
        <text x={lx} y={ly} fill={color} fontSize={7.5}>
          {label}
        </text>
      )}
    </g>
  );
}

export function PathArrow({ d, color = "#8b949e" }: { d: string; color?: string }) {
  return <path d={d} stroke={color} strokeWidth={1.5} fill="none" markerEnd={`url(#${markerId(color)})`} />;
}

export function ArrowMarkerDefs() {
  const defs: Array<[string, string]> = [
    ["arr-gray", "#8b949e"],
    ["arr-blue", "#58a6ff"],
    ["arr-green", "#3fb950"],
    ["arr-red", "#f85149"],
    ["arr-purple", "#a78bfa"],
    ["arr-cyan", "#39d3f2"],
    ["arr-amber", "#f59e0b"],
    ["arr-indigo", "#818cf8"],
  ];
  return (
    <svg style={{ display: "none" }} xmlns="http://www.w3.org/2000/svg">
      <defs>
        {defs.map(([id, color]) => (
          <marker key={id} id={id} markerWidth={7} markerHeight={7} refX={6} refY={3.5} orient="auto">
            <path d="M0,0 L0,7 L7,3.5 z" fill={color} />
          </marker>
        ))}
      </defs>
    </svg>
  );
}

export function WritePipelineDiagram() {
  return (
    <Diagram height={138} caption="State write pipeline — all 5 steps on every accepted write">
      <Box x={5} y={4} w={76} h={26} fill="#0f0f2a" stroke="#818cf8" label="Agent/User" />
      <Arrow x1={81} y1={17} x2={96} y2={17} color="#8b949e" label="_write(key,val)" lx={83} ly={12} />
      <Box x={96} y={4} w={84} h={26} fill="#1a0f00" stroke="#d97706" label="PermGuard" />
      <Arrow x1={180} y1={17} x2={195} y2={17} color="#3fb950" label="write" lx={182} ly={12} />
      <Box x={195} y={4} w={66} h={26} fill="#0d2045" stroke="#58a6ff" label="WorldState" />
      <PathArrow d="M138,30 L138,52 L70,52 L70,74" color="#f85149" />
      <text x={108} y={47} fill="#f85149" fontSize={7.5}>✗ deny</text>
      <Box x={30} y={74} w={78} h={24} fill="#3d0c0c" stroke="#f85149" label="✗ DENIED" fontSize={8} />
      <PathArrow d="M220,30 L220,52 L160,52 L160,74" color="#3fb950" />
      <text x={163} y={47} fill="#3fb950" fontSize={7.5}>record()</text>
      <Box x={118} y={74} w={84} h={24} fill="#0a1f0f" stroke="#3fb950" label="AuditLog" fontSize={8} />
      <PathArrow d="M245,30 L245,74" color="#58a6ff" />
      <text x={248} y={58} fill="#58a6ff" fontSize={7.5}>notify()</text>
      <Box x={208} y={74} w={54} h={24} fill="#1a1200" stroke="#f59e0b" label="Gtwy" fontSize={8} />
      <Arrow x1={235} y1={98} x2={235} y2={116} color="#39d3f2" />
      <text x={238} y={113} fill="#39d3f2" fontSize={7.5}>push()</text>
      <text x={235} y={132} textAnchor="middle" fill="#39d3f2" fontSize={10}>Users</text>
    </Diagram>
  );
}

export function BusFanoutDiagram() {
  return (
    <Diagram height={125} caption="Pub/Sub fan-out — each subscriber gets an independent asyncio.Task">
      <Box x={4} y={44} w={66} h={26} fill="#0f0f2a" stroke="#818cf8" label="Publisher" />
      <Arrow x1={70} y1={57} x2={90} y2={57} color="#a78bfa" label="_publish(topic, payload)" lx={72} ly={52} />
      <Box x={90} y={32} w={74} h={52} fill="#1a0d35" stroke="#a78bfa" label="MessageBus" />
      <text x={127} y={52} textAnchor="middle" fill="#a78bfa" fontSize={7} opacity={0.7}>{"BusMessage{id,topic,"}</text>
      <text x={127} y={61} textAnchor="middle" fill="#a78bfa" fontSize={7} opacity={0.7}>{"sender,payload,ts}"}</text>
      <PathArrow d="M164,43 L184,43 L184,22 L198,22" color="#a78bfa" />
      <PathArrow d="M164,57 L198,57" color="#a78bfa" />
      <PathArrow d="M164,71 L184,71 L184,92 L198,92" color="#a78bfa" />
      <text x={170} y={38} fill="#a78bfa" fontSize={7}>asyncio</text>
      <text x={170} y={46} fill="#a78bfa" fontSize={7}>.Task()</text>
      <Box x={198} y={8} w={64} h={24} fill="#001a1f" stroke="#39d3f2" label="User A" fontSize={8} />
      <Box x={198} y={45} w={64} h={24} fill="#1a1200" stroke="#f59e0b" label="Gateway" fontSize={8} />
      <Box x={198} y={79} w={64} h={24} fill="#0f0f2a" stroke="#818cf8" label="nl_cmd" fontSize={8} />
      <rect x={4} y={106} width={256} height={16} rx={3} fill="#1c2128" />
      <text x={132} y={118} textAnchor="middle" fill="#8b949e" fontSize={8}>Each Task isolated — one failure cannot block others</text>
    </Diagram>
  );
}

export function GatewayBridgeDiagram({ connectedUsers }: { connectedUsers: Array<{ session_id: string }> }) {
  const users = [...connectedUsers.slice(0, 3)];
  while (users.length < 3) users.push(null as unknown as { session_id: string });
  return (
    <Diagram height={150} caption="Gateway — mediator between WebSocket clients and the infrastructure">
      {users.map((u, i) => (
        <Box
          key={i}
          x={4}
          y={10 + i * 40}
          w={74}
          h={28}
          fill={u ? "#001a1f" : "#0d1117"}
          stroke={u ? "#39d3f2" : "#30363d"}
          label={u ? u.session_id.slice(0, 6) : "(empty)"}
          fontSize={8}
        />
      ))}
      {[0, 1, 2].map((i) => (
        <Arrow key={i} x1={78} y1={24 + i * 40} x2={104} y2={65} color="#39d3f2" />
      ))}
      <text x={82} y={50} fill="#39d3f2" fontSize={7}>WebSocket</text>
      <Box x={104} y={44} w={68} h={36} fill="#1a1200" stroke="#f59e0b" label="Gateway" />
      <text x={138} y={68} textAnchor="middle" fill="#f59e0b" fontSize={7} opacity={0.8}>mediator</text>
      <Arrow x1={172} y1={55} x2={194} y2={30} color="#58a6ff" label="watch_any()" lx={174} ly={26} />
      <Box x={194} y={14} w={66} h={28} fill="#0d2045" stroke="#58a6ff" label="WorldState" fontSize={8} />
      <Arrow x1={194} y1={40} x2={172} y2={58} color="#58a6ff" label="notify()" lx={174} ly={58} />
      <Arrow x1={172} y1={67} x2={194} y2={86} color="#a78bfa" label="subscribe()" lx={174} ly={96} />
      <Box x={194} y={70} w={66} h={28} fill="#1a0d35" stroke="#a78bfa" label="MsgBus" fontSize={8} />
      <Arrow x1={194} y1={84} x2={172} y2={72} color="#a78bfa" />
      <rect x={4} y={130} width={256} height={16} rx={3} fill="#1c2128" />
      <text x={132} y={142} textAnchor="middle" fill="#8b949e" fontSize={8}>Each user action: validate role permissions → route to action handler</text>
    </Diagram>
  );
}

export function AuditLogDiagram() {
  return (
    <Diagram height={188} caption="Event sourcing — every system event is recorded as a structured log entry">
      <text x={50} y={14} textAnchor="middle" fill="#818cf8" fontSize={8}>Agent</text>
      <text x={132} y={14} textAnchor="middle" fill="#39d3f2" fontSize={8}>User</text>
      <text x={214} y={14} textAnchor="middle" fill="#a78bfa" fontSize={8}>Bus msg</text>
      <Arrow x1={50} y1={16} x2={50} y2={44} />
      <Arrow x1={132} y1={16} x2={132} y2={44} />
      <Arrow x1={214} y1={16} x2={214} y2={44} />
      <Box x={14} y={44} w={236} h={32} fill="#0a1f0f" stroke="#3fb950" label="AuditLog — append-only, immutable" />
      <text x={132} y={68} textAnchor="middle" fill="#3fb950" fontSize={7.5} opacity={0.8}>
        {"{id, actor, key, value, accepted, event_type, timestamp}"}
      </text>
      <Arrow x1={132} y1={76} x2={132} y2={96} color="#3fb950" label="write()" lx={136} ly={90} />
      <Box x={74} y={96} w={116} h={26} fill="#080c10" stroke="#3fb950" label="session_YYYYMMDD.jsonl" fontSize={8} />
      <Arrow x1={132} y1={122} x2={132} y2={142} color="#3fb950" />
      <Box x={74} y={142} w={116} h={26} fill="#0a1f0f" stroke="#3fb950" label="▶ Replay Viewer" fontSize={8} />
      <text x={14} y={182} fill="#8b949e" fontSize={7.5}>Purposes: reproducibility · accountability · debugging · evaluation</text>
    </Diagram>
  );
}

export function PermGuardDiagram() {
  return (
    <Diagram height={246} caption="Every WorldState write checks capabilities — accept AND deny are both audited">
      <Box x={70} y={4} w={124} h={24} fill="#080c10" stroke="#8b949e" label="agents_config.yaml" fontSize={8} />
      <Arrow x1={132} y1={28} x2={132} y2={46} color="#8b949e" label="parse at startup" lx={136} ly={42} />
      <Box x={60} y={46} w={144} h={24} fill="#1a0f00" stroke="#d97706" label="AgentCapabilities {can_write, can_read}" fontSize={7.5} />
      <Arrow x1={132} y1={70} x2={132} y2={88} color="#d97706" />
      <Box x={70} y={88} w={124} h={24} fill="#1a0f00" stroke="#d97706" label="AgentRegistry.register(cap)" fontSize={8} />
      <Arrow x1={132} y1={112} x2={132} y2={130} color="#d97706" label="lookup on every write" lx={136} ly={126} />
      <Box x={60} y={130} w={144} h={26} fill="#1a0f00" stroke="#f59e0b" label="PermGuard.can_write(actor, key)" fontSize={8} />
      <PathArrow d="M60,143 L30,143 L30,168" color="#3fb950" />
      <text x={8} y={160} fill="#3fb950" fontSize={7.5}>✓ True</text>
      <Box x={4} y={168} w={54} h={22} fill="#0a1f0f" stroke="#3fb950" label="accept" fontSize={8} />
      <PathArrow d="M204,143 L234,143 L234,168" color="#f85149" />
      <text x={210} y={160} fill="#f85149" fontSize={7.5}>✗ False</text>
      <Box x={208} y={168} w={54} h={22} fill="#3d0c0c" stroke="#f85149" label="deny" fontSize={8} />
      <PathArrow d="M31,190 L31,202 L132,202 L132,218" color="#8b949e" />
      <PathArrow d="M235,190 L235,202 L132,202" color="#8b949e" />
      <Box x={74} y={218} w={116} h={24} fill="#0a1f0f" stroke="#3fb950" label="AuditLog (always recorded)" fontSize={7.5} />
    </Diagram>
  );
}

export function ReactiveAgentDiagram({ agentId }: { agentId: string }) {
  return (
    <Diagram height={130} caption="Reactive (watch-based) agent pattern — callback fires on every WorldState write">
      <Box x={4} y={36} w={90} h={28} fill="#0d2045" stroke="#58a6ff" label="WorldState" />
      <text x={49} y={72} textAnchor="middle" fill="#8b949e" fontSize={7.5}>key changes</text>
      <Arrow x1={94} y1={50} x2={116} y2={50} color="#58a6ff" label="watch callback fires" lx={96} ly={44} />
      <Box x={116} y={24} w={80} h={52} fill="#0f0f2a" stroke="#818cf8" label={`${agentId}\n.run()`} />
      <text x={156} y={58} textAnchor="middle" fill="#8b949e" fontSize={7} opacity={0.8}>coroutine awaits</text>
      <text x={156} y={66} textAnchor="middle" fill="#8b949e" fontSize={7} opacity={0.8}>Future()</text>
      <PathArrow d="M196,40 L220,40 L220,18 L234,18" color="#58a6ff" />
      <text x={200} y={35} fill="#58a6ff" fontSize={7}>_write()</text>
      <Box x={234} y={4} w={26} h={28} fill="#0d2045" stroke="#58a6ff" label="WS" fontSize={7} />
      <PathArrow d="M196,60 L220,60 L220,82 L234,82" color="#a78bfa" />
      <text x={200} y={78} fill="#a78bfa" fontSize={7}>_publish()</text>
      <Box x={234} y={68} w={26} h={28} fill="#1a0d35" stroke="#a78bfa" label="MB" fontSize={7} />
      <rect x={4} y={110} width={256} height={16} rx={3} fill="#1c2128" />
      <text x={132} y={122} textAnchor="middle" fill="#8b949e" fontSize={8}>Event-driven — zero polling, reacts in &lt;1ms of state change</text>
    </Diagram>
  );
}

export function LLMAgentDiagram() {
  return (
    <Diagram height={150} caption="Deliberative + tool-use pattern — the LLM decides which tools to call">
      <Box x={4} y={44} w={90} h={26} fill="#1a0d35" stroke="#a78bfa" label="nl_command.request" fontSize={8} />
      <Arrow x1={94} y1={57} x2={112} y2={57} color="#a78bfa" label="bus delivers" lx={96} ly={52} />
      <Box x={112} y={30} w={80} h={54} fill="#0f0f2a" stroke="#818cf8" label="NLCommand\nAgent" />
      <Arrow x1={136} y1={84} x2={136} y2={102} color="#818cf8" label="asyncio.to_thread()" lx={140} ly={98} />
      <Box x={80} y={102} w={144} h={32} fill="#0a0818" stroke="#a78bfa" label="Groq LLM  (LLaMA 3.3 70B)" fontSize={8} />
    </Diagram>
  );
}
