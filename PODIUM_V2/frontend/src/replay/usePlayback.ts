import { useCallback, useEffect, useRef, useState } from "react";
import { fetchRecording, fetchRecordings } from "mivais-va-client";
import type { AuditEntry, ConnectedUser, CursorMap, RecordingInfo } from "mivais-va-client";
import type { PodiumWorldState } from "../types";

export interface RecordedEvent {
  t: number;
  type: "snapshot" | "state_update" | "cursor_update" | "connect" | "disconnect" | "bus_message" | "user_action" | string;
  world_state?: Partial<PodiumWorldState>;
  audit_log?: AuditEntry[];
  cursors?: CursorMap;
  connected_users?: ConnectedUser[];
  session_id?: string;
  role?: string;
  [key: string]: unknown;
}

interface PlaybackState {
  worldState: Partial<PodiumWorldState>;
  auditLog: AuditEntry[];
  cursors: CursorMap;
  connectedUsers: ConnectedUser[];
}

const EMPTY_STATE: PlaybackState = { worldState: {}, auditLog: [], cursors: {}, connectedUsers: [] };

function reduceEvent(state: PlaybackState, ev: RecordedEvent): PlaybackState {
  switch (ev.type) {
    case "snapshot":
    case "state_update":
      return {
        worldState: ev.world_state ? { ...state.worldState, ...ev.world_state } : state.worldState,
        auditLog: ev.audit_log ?? state.auditLog,
        cursors: ev.cursors ?? state.cursors,
        connectedUsers: ev.connected_users ?? state.connectedUsers,
      };
    case "cursor_update":
      return { ...state, cursors: ev.cursors ?? state.cursors, connectedUsers: ev.connected_users ?? state.connectedUsers };
    case "connect":
      if (ev.session_id && ev.role) {
        return {
          ...state,
          connectedUsers: [...state.connectedUsers.filter((u) => u.session_id !== ev.session_id), { session_id: ev.session_id, role: ev.role }],
        };
      }
      return state;
    case "disconnect":
      return { ...state, connectedUsers: state.connectedUsers.filter((u) => u.session_id !== ev.session_id) };
    default:
      return state;
  }
}

function computeStateAt(events: RecordedEvent[], targetT: number): PlaybackState {
  let snapshotIdx = -1;
  for (let i = 0; i < events.length; i++) {
    if (events[i].t > targetT) break;
    if (events[i].type === "snapshot" || events[i].type === "state_update") snapshotIdx = i;
  }
  let state = EMPTY_STATE;
  if (snapshotIdx >= 0) state = reduceEvent(state, events[snapshotIdx]);
  for (let i = snapshotIdx + 1; i < events.length; i++) {
    if (events[i].t > targetT) break;
    state = reduceEvent(state, events[i]);
  }
  return state;
}

export function usePlayback() {
  const [recordings, setRecordings] = useState<RecordingInfo[]>([]);
  const [selected, setSelected] = useState("");
  const [events, setEvents] = useState<RecordedEvent[]>([]);
  const [snapshot, setSnapshot] = useState<PlaybackState>(EMPTY_STATE);
  const [currentT, setCurrentT] = useState(0);
  const [totalT, setTotalT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [loading, setLoading] = useState(false);

  const eventsRef = useRef<RecordedEvent[]>([]);
  const stateRef = useRef<PlaybackState>(EMPTY_STATE);
  const lastAppliedIdx = useRef(-1);
  const playStart = useRef(0);
  const rafHandle = useRef<number | null>(null);

  useEffect(() => {
    fetchRecordings().then(setRecordings).catch(() => {});
  }, []);

  const seekTo = useCallback((targetT: number) => {
    const total = eventsRef.current.length ? eventsRef.current[eventsRef.current.length - 1].t : 0;
    const clamped = Math.max(0, Math.min(targetT, total));
    const state = computeStateAt(eventsRef.current, clamped);
    stateRef.current = state;
    lastAppliedIdx.current = eventsRef.current.findIndex((e) => e.t > clamped) - 1;
    if (lastAppliedIdx.current < -1) lastAppliedIdx.current = eventsRef.current.length - 1;
    setSnapshot(state);
    setCurrentT(clamped);
  }, []);

  const pause = useCallback(() => {
    setPlaying(false);
    if (rafHandle.current) cancelAnimationFrame(rafHandle.current);
    rafHandle.current = null;
  }, []);

  const tick = useCallback(() => {
    const realNow = performance.now();
    let t = (realNow - playStart.current) * speed;
    const total = eventsRef.current.length ? eventsRef.current[eventsRef.current.length - 1].t : 0;

    if (t >= total) {
      t = total;
      let state = stateRef.current;
      while (lastAppliedIdx.current + 1 < eventsRef.current.length) {
        lastAppliedIdx.current++;
        state = reduceEvent(state, eventsRef.current[lastAppliedIdx.current]);
      }
      stateRef.current = state;
      setSnapshot(state);
      setCurrentT(t);
      pause();
      return;
    }

    let state = stateRef.current;
    let changed = false;
    while (lastAppliedIdx.current + 1 < eventsRef.current.length && eventsRef.current[lastAppliedIdx.current + 1].t <= t) {
      lastAppliedIdx.current++;
      state = reduceEvent(state, eventsRef.current[lastAppliedIdx.current]);
      changed = true;
    }
    if (changed) {
      stateRef.current = state;
      setSnapshot(state);
    }
    setCurrentT(t);
    rafHandle.current = requestAnimationFrame(tick);
  }, [speed, pause]);

  const play = useCallback(() => {
    if (playing) return;
    const total = eventsRef.current.length ? eventsRef.current[eventsRef.current.length - 1].t : 0;
    if (currentT >= total) {
      seekTo(0);
    }
    setPlaying(true);
    playStart.current = performance.now() - (currentT >= total ? 0 : currentT) / speed;
    rafHandle.current = requestAnimationFrame(tick);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, currentT, speed, seekTo, tick]);

  const togglePlay = useCallback(() => (playing ? pause() : play()), [playing, pause, play]);

  const changeSpeed = useCallback(
    (s: number) => {
      const wasPlaying = playing;
      if (wasPlaying) pause();
      setSpeed(s);
      if (wasPlaying) {
        // restart the raf clock at the new speed from the current position
        playStart.current = performance.now() - currentT / s;
        setPlaying(true);
        rafHandle.current = requestAnimationFrame(tick);
      }
    },
    [playing, pause, currentT, tick],
  );

  const loadRecording = useCallback(
    async (filename: string) => {
      if (!filename) return;
      setSelected(filename);
      setLoading(true);
      try {
        const text = await fetchRecording(filename);
        const parsed: RecordedEvent[] = text
          .trim()
          .split("\n")
          .filter((l) => l.trim())
          .map((l) => {
            try {
              return JSON.parse(l);
            } catch {
              return null;
            }
          })
          .filter((e): e is RecordedEvent => Boolean(e))
          .sort((a, b) => a.t - b.t);

        eventsRef.current = parsed;
        setEvents(parsed);
        const total = parsed.length ? parsed[parsed.length - 1].t : 0;
        setTotalT(total);
        pause();
        seekTo(0);
      } finally {
        setLoading(false);
      }
    },
    [pause, seekTo],
  );

  useEffect(() => () => pause(), [pause]);

  return {
    recordings,
    selected,
    loadRecording,
    events,
    ...snapshot,
    currentT,
    totalT,
    playing,
    speed,
    loading,
    play,
    pause,
    togglePlay,
    seekTo,
    changeSpeed,
  };
}
