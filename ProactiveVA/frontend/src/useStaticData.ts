import { useEffect, useState } from "react";
import type { StaticData } from "./types";


export function useStaticData(): StaticData | null {
  const [data, setData] = useState<StaticData | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [dataset, hexgrid, streets, entities, knowledge] = await Promise.all([
        fetch("/data/dataset").then((r) => r.json()),
        fetch("/data/hexgrid").then((r) => r.json()),
        fetch("/data/streets").then((r) => r.json()),
        fetch("/data/entities").then((r) => r.json()),
        fetch("/data/knowledge").then((r) => r.json()),
      ]);
      if (!cancelled) setData({ dataset, hexgrid, streets, entities, knowledge });
    })().catch((err) => console.error("[static] failed", err));
    return () => {
      cancelled = true;
    };
  }, []);
  return data;
}
