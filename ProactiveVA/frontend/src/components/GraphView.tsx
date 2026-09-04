import { useEffect, useMemo, useRef } from "react";
import * as d3 from "d3";
import { useProactive } from "../context";
import { entityType, filteredMessages } from "../helpers";
import type { Mc3Message } from "../types";

interface GNode extends d3.SimulationNodeDatum {
  id: string;
  n: number;
}
interface GLink extends d3.SimulationLinkDatum<GNode> {
  n: number;
}

const STOP = new Set([
  "the","a","an","and","or","but","to","of","in","on","at","for","is","are","was","were","be","being","been",
  "this","that","these","those","it","its","i","im","me","my","you","your","we","us","our","they","their","them",
  "so","as","if","have","has","had","will","would","can","could","should","do","does","did","done","here","there",
  "just","now","still","not","no","yes","more","most","some","any","all","one","two","three","dont",
  "rt","via","from","about","out","up","down","than","then","what","who","when","where","why","how",
  "amp","reply","retweet","tweet","watch","see","saw","call","said","says","tell","think","feel","look",
  "POKRally","tag","POK","HI",
]);

export function GraphView({ dataset }: { dataset: Mc3Message[] }) {
  const { worldState, sendAction } = useProactive();
  const svgRef = useRef<SVGSVGElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const simRef = useRef<d3.Simulation<GNode, GLink> | null>(null);
  const nodesRef = useRef<GNode[]>([]);
  const lastSigRef = useRef("");

  // Graph is the entity-dimension navigator — skip its own filter.
  const filtered = useMemo(
    () => filteredMessages(dataset, worldState, "entity"),
    [dataset, worldState.selected_hex, worldState.keyword_filter, worldState.time_range],
  );

  useEffect(() => {
    const node = svgRef.current;
    const host = hostRef.current;
    if (!node || !host) return;
    const w = host.clientWidth;
    const h = host.clientHeight;
    if (!w || !h) return;
    const svg = d3.select(node);

    const ents = new Map<string, number>();
    const cooc = new Map<string, number>();
    for (const m of filtered) {
      const es = m.entities || [];
      for (const e of es) ents.set(e, (ents.get(e) || 0) + 1);
      for (let i = 0; i < es.length; i++)
        for (let j = i + 1; j < es.length; j++) {
          const k = [es[i], es[j]].sort().join("|");
          cooc.set(k, (cooc.get(k) || 0) + 1);
        }
    }
    const sortedIds = Array.from(ents.keys()).sort();
    const newSig = sortedIds.join("|");

    if (!sortedIds.length) {
      svg.selectAll("*").remove();
      svg.append("text").attr("x", 12).attr("y", 20).attr("fill", "#94a3b8").text("No entities in current filter.");
      simRef.current?.stop();
      simRef.current = null;
      nodesRef.current = [];
      lastSigRef.current = "";
      return;
    }

    const r = d3.scaleSqrt().domain([0, d3.max(Array.from(ents.values()))!]).range([4, 24]);

    if (newSig !== lastSigRef.current) {
      svg.selectAll("*").remove();
      lastSigRef.current = newSig;

      const prevById = new Map(nodesRef.current.map((n) => [n.id, n]));
      const nodes: GNode[] = sortedIds.map((id) => {
        const old = prevById.get(id);
        return old ? { ...old, n: ents.get(id)! } : { id, n: ents.get(id)!, x: w / 2, y: h / 2 };
      });
      nodesRef.current = nodes;
      const links: GLink[] = Array.from(cooc, ([k, n]) => {
        const [a, b] = k.split("|");
        return { source: a, target: b, n };
      }).filter((l) => l.n >= 2);

      simRef.current?.stop();
      const sim = d3
        .forceSimulation(nodes)
        .alpha(0.6)
        .alphaDecay(0.08)
        .force("charge", d3.forceManyBody().strength(-80))
        .force("link", d3.forceLink<GNode, GLink>(links).id((d) => d.id).distance(60).strength(0.5))
        .force("center", d3.forceCenter(w / 2, h / 2))
        .force("collide", d3.forceCollide<GNode>((d) => r(d.n) + 4));
      simRef.current = sim;

      const linkSel = svg
        .append("g")
        .attr("class", "links")
        .selectAll("line")
        .data(links)
        .join("line")
        .attr("class", "link")
        .attr("stroke-width", (d) => Math.min(4, d.n / 3));
      const nodeSel = svg
        .append("g")
        .attr("class", "nodes")
        .selectAll("g")
        .data(nodes)
        .join("g")
        .attr("class", (d) => "node t-" + entityType(d.id) + (worldState.selected_entity === d.id ? " selected" : ""))
        .on("click", (_, d) => sendAction({ action: "select_entity", entity: d.id }));
      nodeSel.append("circle").attr("r", (d) => r(d.n));
      nodeSel.append("text").attr("dy", ".35em").attr("text-anchor", "middle").text((d) => d.id);

      sim.on("tick", () => {
        linkSel
          .attr("x1", (d) => (d.source as GNode).x!)
          .attr("y1", (d) => (d.source as GNode).y!)
          .attr("x2", (d) => (d.target as GNode).x!)
          .attr("y2", (d) => (d.target as GNode).y!);
        nodeSel.attr("transform", (d) => `translate(${d.x},${d.y})`);
      });
    } else {
      // Same entity set — update sizes + selection class in place.
      for (const n of nodesRef.current) n.n = ents.get(n.id)!;
      svg
        .select(".nodes")
        .selectAll<SVGGElement, GNode>("g")
        .attr("class", (d) => "node t-" + entityType(d.id) + (worldState.selected_entity === d.id ? " selected" : ""))
        .select("circle")
        .attr("r", (d) => r(d.n));
    }
  }, [filtered, worldState.selected_entity, sendAction]);

  // Word cloud — same filtered set, so it stays linked.
  const top = useMemo(() => {
    const counts = new Map<string, number>();
    for (const m of filtered) {
      const tokens = (m.message || "").toLowerCase().match(/[a-z]{3,}/g) || [];
      for (const t of tokens) {
        if (STOP.has(t)) continue;
        counts.set(t, (counts.get(t) || 0) + 1);
      }
    }
    return Array.from(counts).sort((a, b) => b[1] - a[1]).slice(0, 36);
  }, [filtered]);
  const maxN = top.length ? top[0][1] : 1;

  return (
    <>
      <div id="graph-svg-host" ref={hostRef}>
        <svg id="graph-svg" ref={svgRef} />
      </div>
      <div id="wordcloud">
        {top.length ? (
          top.map(([w, n]) => (
            <span
              key={w}
              className="w"
              style={{ fontSize: 9 + Math.round(12 * Math.sqrt(n / maxN)) }}
              onClick={() => {
                const cur = (worldState.keyword_filter || []).slice();
                if (!cur.includes(w)) sendAction({ action: "set_keyword_filter", keywords: [...cur, w] });
              }}
            >
              {w}
            </span>
          ))
        ) : (
          <div className="empty-hint" style={{ padding: 0 }}>
            No words yet.
          </div>
        )}
      </div>
    </>
  );
}
