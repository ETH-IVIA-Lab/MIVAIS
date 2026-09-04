import cytoscape from "cytoscape";
import type { Core, EventObject } from "cytoscape";
import { useEffect, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import { CY_STYLE, STATIC_EDGES, STATIC_NODES, TOOLTIPS } from "./cytoscapeSetup";
import type { TooltipState } from "./Tooltip";

export interface TopologyGraphProps {
  onReady: (cy: Core) => void;
  onNodeTap: (nodeId: string) => void;
  onBackgroundTap: () => void;
  onTooltip: Dispatch<SetStateAction<TooltipState | null>>;
}

export function TopologyGraph({ onReady, onNodeTap, onBackgroundTap, onTooltip }: TopologyGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      style: CY_STYLE,
      elements: { nodes: STATIC_NODES, edges: STATIC_EDGES },
      layout: { name: "preset" },
      zoomingEnabled: true,
      userZoomingEnabled: true,
      panningEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
      minZoom: 0.2,
      maxZoom: 3,
    });

    setTimeout(() => cy.fit(cy.nodes(), 80), 120);

    cy.on("tap", "node", (e: EventObject) => {
      if (e.target.hasClass("packet")) return;
      onNodeTap(e.target.id());
    });
    cy.on("tap", (e: EventObject) => {
      if (e.target === cy) onBackgroundTap();
    });
    cy.on("dblclick", "node", (e: EventObject) => {
      if (e.target.hasClass("packet")) return;
      cy.animate({ fit: { eles: e.target, padding: 120 } }, { duration: 400, easing: "ease-out" });
    });
    cy.on("mouseover", "node", (e: EventObject) => {
      if (e.target.hasClass("packet")) return;
      const id = e.target.id();
      const info = TOOLTIPS[id] ?? (id.startsWith("user:") ? { title: id, desc: `Connected user (${e.target.data("role") || "observer"}). Click to inspect.` } : null);
      if (!info) return;
      const pos = e.originalEvent as MouseEvent;
      onTooltip({ x: pos.clientX, y: pos.clientY, title: info.title, desc: info.desc });
    });
    cy.on("mouseout", "node", () => onTooltip(null));
    cy.on("mousemove", (e: EventObject) => {
      const pos = e.originalEvent as MouseEvent;
      onTooltip((prev) => (prev ? { ...prev, x: pos.clientX, y: pos.clientY } : prev));
    });

    onReady(cy);
    return () => cy.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div id="cy" ref={containerRef} />;
}
