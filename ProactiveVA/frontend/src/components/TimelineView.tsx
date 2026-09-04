import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { useProactive } from "../context";
import { filteredMessages, fmtClock } from "../helpers";
import type { Mc3Message } from "../types";

export function TimelineView({ dataset }: { dataset: Mc3Message[] }) {
  const { worldState, sendAction } = useProactive();
  const svgRef = useRef<SVGSVGElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = svgRef.current;
    const host = hostRef.current;
    if (!node || !host) return;

    const render = () => {
      const svg = d3.select(node);
      const w = host.clientWidth || 400;
      const h = host.clientHeight || 180;
      svg.attr("viewBox", `0 0 ${w} ${h}`).selectAll("*").remove();

      
      const msgs = filteredMessages(dataset, worldState, "time");
      if (!msgs.length) return;

      const margin = { top: 8, right: 10, bottom: 24, left: 32 };
      const innerW = Math.max(40, w - margin.left - margin.right);
      const innerH = Math.max(20, h - margin.top - margin.bottom);
      const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

      const bucketSize = 300; // 5-minute buckets
      const ext = d3.extent(msgs, (d) => d.epoch) as [number, number];
      const t0 = Math.floor(ext[0] / bucketSize) * bucketSize;
      const t1 = Math.ceil(ext[1] / bucketSize) * bucketSize;
      const buckets = new Map<number, { t: number; n: number; pos: number; neg: number }>();
      for (let t = t0; t <= t1; t += bucketSize) buckets.set(t, { t, n: 0, pos: 0, neg: 0 });
      for (const d of msgs) {
        const t = Math.floor((d.epoch || 0) / bucketSize) * bucketSize;
        const b = buckets.get(t);
        if (!b) continue;
        b.n += 1;
        if (d.sentiment === "positive") b.pos += 1;
        else if (d.sentiment === "negative") b.neg += 1;
      }
      const items = Array.from(buckets.values()).sort((a, b) => a.t - b.t);

      const x = d3.scaleLinear().domain([t0, t1 + bucketSize]).range([0, innerW]);
      const yMax = d3.max(items, (d) => d.n) || 1;
      const y = d3.scaleLinear().domain([0, yMax]).nice().range([innerH, 0]);
      const bw = Math.max(1, innerW / items.length - 0.5);

      g.append("g")
        .attr("transform", `translate(0,${innerH})`)
        .call(d3.axisBottom(x).ticks(6).tickFormat((t) => fmtClock(Number(t))))
        .call((sel) => sel.selectAll("text").style("font-size", "9px").style("fill", "#64748b"))
        .call((sel) => sel.selectAll("line, path").style("stroke", "#cbd5e1"));

      g.append("g")
        .call(d3.axisLeft(y).ticks(4))
        .call((sel) => sel.selectAll("text").style("font-size", "9px").style("fill", "#64748b"))
        .call((sel) => sel.selectAll("line, path").style("stroke", "#cbd5e1"));

      g.append("g")
        .selectAll("rect")
        .data(items)
        .join("rect")
        .attr("class", (d) => "tl-bar " + (d.neg > d.pos ? "s-negative" : d.pos > d.neg ? "s-positive" : ""))
        .attr("x", (d) => x(d.t))
        .attr("y", (d) => y(d.n))
        .attr("width", bw)
        .attr("height", (d) => innerH - y(d.n))
        .append("title")
        .text((d) => `${fmtClock(d.t)} — ${d.n} msg`);

      const brush = d3
        .brushX()
        .extent([
          [0, 0],
          [innerW, innerH],
        ])
        .on("end", (e) => {
          if (!e.sourceEvent) return; 
          if (!e.selection) {
            sendAction({ action: "set_time_range", start: null, end: null });
            return;
          }
          const [a, b] = (e.selection as [number, number]).map(x.invert);
          sendAction({ action: "set_time_range", start: a, end: b });
        });
      const brushG = g.append("g").attr("class", "brush").call(brush);
      const tr = worldState.time_range;
      if (tr && tr.start != null && tr.end != null) {
        brushG.call(brush.move, [x(tr.start), x(tr.end)]);
      }
    };

    render();
    const ro = new ResizeObserver(render);
    ro.observe(host);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    dataset,
    worldState.selected_hex,
    worldState.selected_entity,
    worldState.keyword_filter,
    worldState.time_range,
  ]);

  return (
    <div ref={hostRef} style={{ position: "absolute", inset: 0 }}>
      <svg id="timeline-svg" ref={svgRef} />
    </div>
  );
}
