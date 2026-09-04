import { useEffect, useRef, useState } from "react";
import embed from "vega-embed";
import { buildVegaLiteSpec } from "../vegaSpec";
import type { ChartFilter } from "../vegaSpec";
import type { ViewSpec } from "../types";

export interface VegaChartProps {
  spec: ViewSpec | null | undefined;
  dataset: unknown[];
  width?: number;
  height?: number;
  renderer?: "svg" | "canvas";
  lazy?: boolean;
  emptyText?: string;
  className?: string;
  /** Thumbnail mode: no in-chart title, tighter axis/legend labels. */
  compact?: boolean;
  /** Shared filters applied as a vega-lite transform. */
  filters?: ChartFilter[];
}


export function VegaChart({
  spec,
  dataset,
  width,
  height,
  renderer = "svg",
  lazy = false,
  emptyText = "No chart to display",
  className,
  compact = false,
  filters = [],
}: VegaChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const lastHash = useRef<string | null>(null);
  const [visible, setVisible] = useState(!lazy);

  useEffect(() => {
    if (!lazy || visible) return;
    const el = containerRef.current;
    if (!el || !("IntersectionObserver" in window)) {
      setVisible(true);
      return;
    }
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          obs.disconnect();
        }
      },
      { rootMargin: "300px 0px", threshold: 0.01 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [lazy, visible]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !visible) return;

    if (!spec) {
      el.innerHTML = `<div class="focus-placeholder">${emptyText}</div>`;
      lastHash.current = null;
      return;
    }

    const vlSpec = buildVegaLiteSpec(spec, dataset, width, height, compact, filters);
    if (!vlSpec) {
      el.innerHTML = `<div class="focus-placeholder">Invalid specification</div>`;
      return;
    }

    const hash = JSON.stringify(vlSpec);
    if (lastHash.current === hash) return;
    lastHash.current = hash;

    el.innerHTML = "";
    embed(el, vlSpec as never, { actions: false, renderer }).catch((err: Error) => {
      el.innerHTML = `<div class="focus-placeholder" style="color:var(--red);font-size:11px;">Render error: ${err.message}</div>`;
    });
  }, [spec, dataset, width, height, renderer, visible, emptyText, compact, filters]);

  return (
    <div ref={containerRef} className={className} style={lazy && height ? { minHeight: height } : undefined}>
      {!visible && <div className="focus-placeholder" style={{ fontSize: 10, color: "var(--text-secondary)" }}>…</div>}
    </div>
  );
}
