import { useCallback, useEffect, useRef, useState } from "react";
import { apiPost } from "../../lib/api";

export type ReplayVAStatus = "idle" | "starting" | "connecting" | "ready" | "error";

interface StartResponse {
  iframe_url: string;
  va_system_id: string;
  replay_ws_url: string;
  port: number;
}


export function useReplayVA(sessionId: string, enabled: boolean) {
  const [status, setStatus] = useState<ReplayVAStatus>("idle");
  const [iframeUrl, setIframeUrl] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const readyRef = useRef(false);

  const pushState = useCallback((state: Record<string, unknown>) => {
    if (!readyRef.current || !wsRef.current || !state) return;
    wsRef.current.send(JSON.stringify({ action: "replay.push_state", state }));
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    (async () => {
      setStatus("starting");
      let res: StartResponse;
      try {
        res = await apiPost<StartResponse>(`/api/admin/replay/${sessionId}/start`);
      } catch {
        if (!cancelled) setStatus("error");
        return;
      }
      if (cancelled) return;
      setIframeUrl(res.iframe_url);
      setStatus("connecting");
      const ws = new WebSocket(res.replay_ws_url);
      wsRef.current = ws;
      ws.onopen = () => {
        readyRef.current = true;
        if (!cancelled) setStatus("ready");
      };
      ws.onerror = () => {
        if (!cancelled) setStatus("error");
      };
      ws.onclose = () => {
        readyRef.current = false;
      };
      ws.onmessage = () => {}; 
    })();

    return () => {
      cancelled = true;
      readyRef.current = false;
      wsRef.current?.close();
      wsRef.current = null;
      apiPost(`/api/admin/replay/${sessionId}/stop`).catch(() => {});
    };
  }, [sessionId, enabled]);

  
  useEffect(() => {
    if (!enabled) return;
    const onUnload = () => {
      try {
        navigator.sendBeacon(`/api/admin/replay/${sessionId}/stop`);
      } catch {
        // ignore
      }
    };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, [sessionId, enabled]);

  return { status, iframeUrl, pushState };
}
