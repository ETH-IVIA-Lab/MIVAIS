import { useEffect, useState } from "react";
import { connect, getStatus, subscribe, type HRStatus } from "../lib/heartRateMonitor";

export function useHeartRateMonitor() {
  const [status, setStatus] = useState<HRStatus>(() => getStatus().status);
  const [bpm, setBpm] = useState<number | null>(() => getStatus().bpm);
  const supported = typeof navigator !== "undefined" && !!navigator.bluetooth;

  useEffect(() => subscribe((s, b) => {
    setStatus(s);
    setBpm(b);
  }), []);

  return { status, bpm, supported, connect };
}
