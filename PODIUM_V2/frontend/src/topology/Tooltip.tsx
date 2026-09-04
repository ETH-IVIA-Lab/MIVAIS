export interface TooltipState {
  x: number;
  y: number;
  title: string;
  desc: string;
}

export function Tooltip({ tooltip }: { tooltip: TooltipState | null }) {
  if (!tooltip) return <div id="tooltip" />;
  return (
    <div id="tooltip" className="visible" style={{ left: tooltip.x + 14, top: tooltip.y + 14 }}>
      <h4>{tooltip.title}</h4>
      <p>{tooltip.desc}</p>
    </div>
  );
}
