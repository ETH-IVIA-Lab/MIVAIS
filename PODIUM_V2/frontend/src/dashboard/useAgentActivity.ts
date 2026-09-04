import { useEffect, useRef, useState } from "react";
import { usePodium } from "../context";

export interface AgentActivity {
  pillOn: boolean;
  glowOn: boolean;
  glowNonce: number;
  scanOn: boolean;
  scanNonce: number;
  thinkOn: boolean;
  busBadgeOn: boolean;
}


export function useAgentActivity(actorId: string): AgentActivity {
  const { subscribeNewAuditEntries } = usePodium();
  const [pillOn, setPillOn] = useState(false);
  const [glowOn, setGlowOn] = useState(false);
  const [glowNonce, setGlowNonce] = useState(0);
  const [scanOn, setScanOn] = useState(false);
  const [scanNonce, setScanNonce] = useState(0);
  const [thinkOn, setThinkOn] = useState(false);
  const [busBadgeOn, setBusBadgeOn] = useState(false);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  useEffect(() => {
    return subscribeNewAuditEntries((entries) => {
      const mine = entries.filter((e) => e.actor === actorId);
      if (!mine.length) return;

      const fire = (key: string, setOn: (v: boolean) => void, duration: number, bump?: () => void) => {
        clearTimeout(timers.current[key]);
        setOn(true);
        bump?.();
        timers.current[key] = setTimeout(() => setOn(false), duration);
      };

      fire("pill", setPillOn, 3500);
      fire("glow", setGlowOn, 2800, () => setGlowNonce((n) => n + 1));
      fire("scan", setScanOn, 750, () => setScanNonce((n) => n + 1));
      fire("think", setThinkOn, 2400);
      if (mine.some((e) => e.event_type === "bus_message")) {
        fire("bus", setBusBadgeOn, 1700);
      }
    });
  }, [subscribeNewAuditEntries, actorId]);

  useEffect(
    () => () => {
      Object.values(timers.current).forEach(clearTimeout);
    },
    [],
  );

  return { pillOn, glowOn, glowNonce, scanOn, scanNonce, thinkOn, busBadgeOn };
}
