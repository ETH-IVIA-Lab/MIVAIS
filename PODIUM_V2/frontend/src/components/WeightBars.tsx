import { useEffect, useRef, useState } from "react";

export function WeightBars({ numericCols, weights }: { numericCols: string[]; weights: Record<string, number> }) {
  const prevWeights = useRef<Record<string, number>>({});
  const [flashCols, setFlashCols] = useState<Set<string>>(new Set());

  useEffect(() => {
    const changed = new Set<string>();
    numericCols.forEach((c) => {
      if ((prevWeights.current[c] ?? 0) !== (weights[c] ?? 0)) changed.add(c);
    });
    if (changed.size && Object.keys(prevWeights.current).length) {
      setFlashCols(changed);
      const t = setTimeout(() => setFlashCols(new Set()), 600);
      prevWeights.current = weights;
      return () => clearTimeout(t);
    }
    prevWeights.current = weights;
  }, [weights, numericCols]);

  if (!numericCols.length || !Object.keys(weights).length) return <div className="weight-bars" />;
  const maxAbs = Math.max(...Object.values(weights).map((w) => Math.abs(w)), 0.001);

  return (
    <div className="weight-bars">
      {numericCols.map((col) => {
        const w = weights[col] ?? 0;
        const pct = ((Math.abs(w) / maxAbs) * 100).toFixed(1);
        return (
          <div key={col} className={`w-row${flashCols.has(col) ? " flash" : ""}`}>
            <span className="w-label">{col}</span>
            <div className="w-track">
              <div className={`w-fill ${w >= 0 ? "w-pos" : "w-neg"}`} style={{ width: `${pct}%` }} />
            </div>
            <span className="w-val">
              {w >= 0 ? "+" : ""}
              {w.toFixed(3)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
