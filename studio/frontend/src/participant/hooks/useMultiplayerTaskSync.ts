import { useEffect, useState } from "react";
import { apiGet } from "../../lib/api";
import type { ParticipantStateResponse } from "../../lib/types";

export function useMultiplayerTaskSync(enabled: boolean, myIndex: number | undefined, onAdvance: () => void): number | null {
  const [etaSeconds, setEtaSeconds] = useState<number | null>(null);

  useEffect(() => {
    if (!enabled || myIndex === undefined) {
      setEtaSeconds(null);
      return;
    }
    const timer = setInterval(async () => {
      try {
        const data = await apiGet<ParticipantStateResponse>("/api/p/state");
        if (typeof data.session_task_index === "number" && data.session_task_index !== myIndex) {
          onAdvance();
          return;
        }
        setEtaSeconds(typeof data.seconds_until_auto_advance === "number" ? data.seconds_until_auto_advance : null);
      } catch {
        // transient network hiccup
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [enabled, myIndex, onAdvance]);

  return etaSeconds;
}
