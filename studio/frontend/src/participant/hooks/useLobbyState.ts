import { useEffect, useState } from "react";
import { apiGet } from "../../lib/api";
import type { LobbyStateResponse } from "../../lib/types";

export function useLobbyState(enabled: boolean) {
  const [state, setState] = useState<LobbyStateResponse | null>(null);
  const [released, setReleased] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const data = await apiGet<LobbyStateResponse>("/api/p/lobby/state");
        if (cancelled) return;
        if (data.released) {
          setReleased(true);
          return;
        }
        setState(data);
      } catch {
        // transient network hiccup; retry next tick
      }
    };
    poll();
    const timer = setInterval(poll, 1500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [enabled]);

  return { state, released };
}
