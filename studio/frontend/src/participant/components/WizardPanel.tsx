import { useEffect, useState } from "react";
import { apiGet, apiPost, ApiError } from "../../lib/api";
import type { WizardPeer } from "../../lib/types";

interface LogLine {
  t: string;
  msg: string;
  kind: "" | "ok" | "warn" | "error";
}

function WizardLog({ lines }: { lines: LogLine[] }) {
  return (
    <div className="wizard-log">
      {lines.map((l, i) => (
        <div
          key={i}
          className={`wz-log-line ${l.kind}`}
          dangerouslySetInnerHTML={{ __html: `<span class="muted small">${l.t}</span> ${l.msg}` }}
        />
      ))}
    </div>
  );
}

function pushLog(lines: LogLine[], msg: string, kind: LogLine["kind"] = ""): LogLine[] {
  return [{ t: new Date().toLocaleTimeString(), msg, kind }, ...lines].slice(0, 12);
}

export function WizardPanel() {
  const [collapsed, setCollapsed] = useState(false);
  const [tab, setTab] = useState<"agents" | "advance" | "peers">("agents");
  const [agents, setAgents] = useState<string[]>([]);
  const [agent, setAgent] = useState("");
  const [sayText, setSayText] = useState("");
  const [key, setKey] = useState("");
  const [valueJson, setValueJson] = useState("");
  const [agentLog, setAgentLog] = useState<LogLine[]>([]);
  const [advanceLog, setAdvanceLog] = useState<LogLine[]>([]);
  const [peers, setPeers] = useState<WizardPeer[]>([]);

  useEffect(() => {
    const handler = (ev: MessageEvent) => {
      const d = ev.data as { kind?: string; agents?: Array<{ id?: string; agent_id?: string } | string> };
      if (!d || d.kind !== "agents" || !Array.isArray(d.agents)) return;
      const ids = d.agents
        .map((a) => (typeof a === "string" ? a : a.id || a.agent_id))
        .filter((x): x is string => !!x);
      setAgents(ids);
      setAgent((prev) => prev || ids[0] || "");
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const data = await apiGet<{ peers: WizardPeer[] }>("/api/p/wizard/peers");
        if (!cancelled) setPeers(data.peers);
      } catch {
        // transient
      }
    };
    poll();
    const timer = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  async function onSay() {
    if (!agent) {
      setAgentLog((l) => pushLog(l, "pick an agent first", "warn"));
      return;
    }
    if (!sayText.trim()) {
      setAgentLog((l) => pushLog(l, "message required", "warn"));
      return;
    }
    try {
      await apiPost("/api/p/wizard/agent_say", { actor: agent, text: sayText.trim() });
      setAgentLog((l) => pushLog(l, `<strong>${agent}</strong> said &ldquo;${sayText.slice(0, 40)}&rdquo;`, "ok"));
      setSayText("");
    } catch (err) {
      setAgentLog((l) => pushLog(l, `failed ${err instanceof ApiError ? err.message : "unknown error"}`, "error"));
    }
  }

  async function onApply() {
    if (!agent) {
      setAgentLog((l) => pushLog(l, "pick an agent first", "warn"));
      return;
    }
    if (!key.trim()) {
      setAgentLog((l) => pushLog(l, "key required", "warn"));
      return;
    }
    try {
      await apiPost("/api/p/wizard/agent_write", { actor: agent, key: key.trim(), value_json: valueJson });
      setAgentLog((l) => pushLog(l, `<strong>${agent}</strong> → <code>${key}</code>`, "ok"));
    } catch (err) {
      setAgentLog((l) => pushLog(l, `failed ${err instanceof ApiError ? err.message : "unknown error"}`, "error"));
    }
  }

  async function onAdvance() {
    try {
      const data = await apiPost<{ scope: string }>("/api/p/wizard/advance");
      setAdvanceLog((l) => pushLog(l, `advanced (${data.scope})`, "ok"));
      setTimeout(() => window.location.reload(), 500);
    } catch {
      setAdvanceLog((l) => pushLog(l, "failed", "error"));
    }
  }

  return (
    <aside className={`wizard-panel ${collapsed ? "collapsed" : ""}`}>
      <header className="wizard-head">
        <strong>Wizard panel</strong>
        <button type="button" className="btn ghost wizard-collapse" title="Collapse" onClick={() => setCollapsed((c) => !c)}>
          –
        </button>
      </header>
      <div className="wizard-body">
        <nav className="wizard-tabs">
          <button type="button" className={tab === "agents" ? "active" : ""} onClick={() => setTab("agents")}>
            Agents
          </button>
          <button type="button" className={tab === "advance" ? "active" : ""} onClick={() => setTab("advance")}>
            Flow
          </button>
          <button type="button" className={tab === "peers" ? "active" : ""} onClick={() => setTab("peers")}>
            Peers
          </button>
        </nav>

        {tab === "agents" && (
          <section className="wizard-tab">
            <p className="muted small">
              Act <strong>as an agent</strong>. Everything here is attributed to that agent (the participant sees
              the AI act) — you can drive the AI fully, but never act as a user.
            </p>
            <label className="field">
              Agent
              <input
                type="text"
                list="wz-agents"
                value={agent}
                onChange={(e) => setAgent(e.target.value)}
                placeholder="e.g. svm_ranker"
                autoComplete="off"
              />
              <datalist id="wz-agents">
                {agents.map((a) => (
                  <option key={a} value={a} />
                ))}
              </datalist>
            </label>

            <div className="wz-block">
              <label className="field">
                Say — chat as this agent
                <input type="text" value={sayText} onChange={(e) => setSayText(e.target.value)} placeholder="Type a message…" />
              </label>
              <button type="button" className="btn primary" onClick={onSay}>
                Send as agent
              </button>
            </div>

            <div className="wz-block">
              <label className="field">
                Set value — WorldState key, as this agent
                <input type="text" value={key} onChange={(e) => setKey(e.target.value)} placeholder="weights" />
              </label>
              <label className="field">
                Value (JSON)
                <textarea
                  rows={2}
                  value={valueJson}
                  onChange={(e) => setValueJson(e.target.value)}
                  placeholder='{"mpg": 0.6}  or  42'
                />
              </label>
              <button type="button" className="btn" onClick={onApply}>
                Apply as agent
              </button>
            </div>
            <WizardLog lines={agentLog} />
          </section>
        )}

        {tab === "advance" && (
          <section className="wizard-tab">
            <p className="muted small">Force the cohort (multiplayer) or yourself (singleplayer) to the next task immediately.</p>
            <button type="button" className="btn primary" onClick={onAdvance}>
              Advance now
            </button>
            <WizardLog lines={advanceLog} />
          </section>
        )}

        {tab === "peers" && (
          <section className="wizard-tab">
            <p className="muted small">Other participants in this session. Updates every 2 s.</p>
            <div>
              {peers.length === 0 && <span className="muted small">No other participants yet.</span>}
              {peers.map((p) => (
                <div key={p.id} className={`wz-peer ${p.is_self ? "self" : ""}`}>
                  <div>
                    <code>{p.anon_id}</code>
                    {p.is_self && <span className="muted small"> (you)</span>}
                  </div>
                  <div className="muted small">
                    {p.role || "—"} · {p.status} {p.task_id ? `· ${p.task_id}` : ""}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </aside>
  );
}
