import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AGENT_NEUTRAL, CAT_COLOR, categoryColor, classifyTimeline, userColor } from "./classify";
import type { AbsentSpan, ClassifiedEvent, EventCategory, Lane, ReplayCursor, ReplayEvent, ReplayPayload, ReplayVideo } from "./types";

export const LANE_STEP = 24;

export interface FilterDef {
  key: string;
  label: string;
  color: string;
  group: "action" | "agent" | "system";
}

const ACTION_FILTERS: Array<{ key: EventCategory; label: string; on: boolean }> = [
  { key: "cursor", label: "Mouse", on: false },
  { key: "ranking", label: "Ranking", on: true },
  { key: "chat", label: "Chat", on: true },
  { key: "agent", label: "Agent activity", on: true },
  { key: "task", label: "Tasks", on: true },
  { key: "presence", label: "Presence", on: true },
];

function userLabel(pid: string, participants: ReplayPayload["participants"]): string {
  const p = participants[pid];
  if (p?.anon_id) return p.role ? `${p.anon_id} · ${p.role}` : p.anon_id;
  return `user ${pid.slice(-4)}`;
}


export interface WorldStateDelta {
  delta: Record<string, { from: unknown; to: unknown }>;
  cause: { label: string; color: string };
}


function computeDeltas(classified: ClassifiedEvent[], snapshots: Record<string, unknown>[]): (WorldStateDelta | null)[] {
  const out: (WorldStateDelta | null)[] = new Array(classified.length).fill(null);
  let prev: Record<string, unknown> | null = null;
  for (let i = 0; i < classified.length; i++) {
    const ev = classified[i];
    if (ev.snapshot_index === undefined) continue;
    const snap = snapshots[ev.snapshot_index] || {};
    const delta: Record<string, { from: unknown; to: unknown }> = {};
    if (prev) {
      const keys = new Set([...Object.keys(prev), ...Object.keys(snap)]);
      for (const k of keys) {
        if (k === "dataset") continue;
        if (JSON.stringify(prev[k]) !== JSON.stringify(snap[k])) delta[k] = { from: prev[k], to: snap[k] };
      }
    }
    
    let cause = { label: "system", color: "var(--ink-muted)" };
    for (let j = i; j >= 0; j--) {
      const e2 = classified[j];
      const m2 = e2.meta || {};
      if (e2.type === "agent_action") {
        const actor = String(m2.actor || "agent");
        cause = { label: actor.replace(/_/g, " "), color: AGENT_NEUTRAL };
        break;
      }
      if (e2.type === "user_action") {
        const w = String(m2.actor || "").replace(/^user:/, "").slice(0, 6);
        const color = e2.participant_id ? userColor(e2.participant_id) : "var(--color-brand-500)";
        cause = { label: w ? `user ${w}` : "user", color };
        break;
      }
    }
    out[i] = { delta, cause };
    prev = snap;
  }
  return out;
}

export function useReplayEngine(payload: ReplayPayload) {
  const classified = useMemo(
    () => classifyTimeline(payload.timeline, payload.categories),
    [payload.timeline, payload.categories],
  );
  const deltas = useMemo(() => computeDeltas(classified, payload.snapshots), [classified, payload.snapshots]);
  const tMax = payload.t_max || 1;

  const agents = useMemo(
    () => [...new Set(classified.filter((e) => e._c.actor).map((e) => e._c.actor!))].sort(),
    [classified],
  );

  const USER_CATS = useMemo(() => new Set(["cursor", "ranking", "chat", "presence"]), []);
  const userLaneKeys = useMemo(() => {
    const users = [...new Set(classified.filter((e) => USER_CATS.has(e._c.cat) && e.participant_id).map((e) => e.participant_id!))];
    return users;
  }, [classified, USER_CATS]);

  
  const hasUnattributedUserEvents = useMemo(
    () => classified.some((e) => USER_CATS.has(e._c.cat) && !e.participant_id),
    [classified, USER_CATS],
  );

  const hasStudio = useMemo(() => classified.some((e) => e.source === "studio"), [classified]);
  const hasMedia = useMemo(() => classified.some((e) => e.source === "audio" || e.source === "transcript"), [classified]);

  const lanes: Lane[] = useMemo(() => {
  
    const userLanes: Lane[] = userLaneKeys.map((pid) => ({
      key: `user:${pid}`,
      label: userLabel(pid, payload.participants),
      color: userColor(pid),
    }));
    if (userLanes.length === 0 || hasUnattributedUserEvents) {
      userLanes.push({ key: "participant", label: "Participant", color: "var(--color-brand-500)" });
    }
    const agentLanes: Lane[] = agents.map((a) => ({ key: `agent:${a}`, label: a.replace(/_/g, " "), color: AGENT_NEUTRAL }));
    return [
      ...userLanes,
      ...agentLanes,
      ...(hasStudio ? [{ key: "studio", label: "Studio", color: CAT_COLOR.task }] : []),
      ...(hasMedia ? [{ key: "media", label: "Media", color: CAT_COLOR.state }] : []),
    ];
  }, [userLaneKeys, agents, hasStudio, hasMedia, hasUnattributedUserEvents, payload.participants]);

  const laneIndex = useMemo(() => Object.fromEntries(lanes.map((l, i) => [l.key, i])), [lanes]);
  const svgHeight = Math.max(1, lanes.length) * LANE_STEP;

  // ── agent absence ────────────────────────────────────────────────
  const taskSpans = useMemo(() => {
    const spans: Array<{ task_id: string; t0: number; t1: number }> = [];
    let open: { task_id: string; t0: number } | null = null;
    for (const ev of classified) {
      if (ev.type === "task_start" && ev.task_id) {
        if (open) spans.push({ ...open, t1: ev.t_ms });
        open = { task_id: ev.task_id, t0: ev.t_ms };
      } else if (ev.type === "task_end" && open) {
        spans.push({ ...open, t1: ev.t_ms });
        open = null;
      }
    }
    if (open) spans.push({ ...open, t1: payload.t_max || open.t0 });
    return spans;
  }, [classified, payload.t_max]);

  const agentVaSystems = useMemo(() => {
    const m: Record<string, Set<string>> = {};
    for (const ev of classified) {
      if (ev._c.actor && ev.va) (m[ev._c.actor] ??= new Set()).add(ev.va);
    }
    return m;
  }, [classified]);

  const absentSpans: Record<string, AbsentSpan[]> = useMemo(() => {
    const taskVa = payload.task_va;
    if (!taskVa) return {};
    const out: Record<string, AbsentSpan[]> = {};
    for (const a of agents) {
      const vas = agentVaSystems[a];
      const spans: AbsentSpan[] = [];
      for (const s of taskSpans) {
        const va = taskVa[s.task_id];
        if (va === undefined) continue; 
        if (va === null) {
          spans.push({ t0: s.t0, t1: s.t1, reason: "no VA on screen (question task)" });
        } else if (vas && vas.size > 0 && !vas.has(va)) {
          spans.push({ t0: s.t0, t1: s.t1, reason: `different VA on screen (${va})` });
        }
      }
      if (spans.length) out[`agent:${a}`] = spans;
    }
    return out;
  }, [agents, agentVaSystems, taskSpans, payload.task_va]);

  const userLaneKeySet = useMemo(() => new Set(userLaneKeys.map((pid) => `user:${pid}`)), [userLaneKeys]);
  const laneOf = useCallback(
    (ev: ClassifiedEvent): string => {
      
      if (ev._c.actor) return `agent:${ev._c.actor}`;
      if (ev.source === "studio") return "studio";
      if (ev.source === "audio" || ev.source === "transcript") return "media";
      if (ev.participant_id && userLaneKeySet.has(`user:${ev.participant_id}`)) return `user:${ev.participant_id}`;
      return "participant";
    },
    [userLaneKeySet],
  );

  
  const categoryLabelOverrides = useMemo(() => {
    const m: Record<string, string> = {};
    for (const d of payload.categories || []) if (d.label) m[d.key] = d.label;
    return m;
  }, [payload.categories]);
  const colorForCat = useCallback(
    (cat: string) => classified.find((e) => e._c.cat === cat)?._c.color || CAT_COLOR[cat] || categoryColor(cat),
    [classified],
  );

  
  const BUILTIN_FILTER_CATS = useMemo(() => new Set<string>([...ACTION_FILTERS.map((f) => f.key), "state", "other"]), []);
  const extraCategories = useMemo(
    () => [...new Set(classified.map((e) => e._c.cat))].filter((c) => !BUILTIN_FILTER_CATS.has(c)).sort(),
    [classified, BUILTIN_FILTER_CATS],
  );

  const filters: FilterDef[] = useMemo(
    () => [
      ...ACTION_FILTERS.map((f) => ({ key: f.key, label: categoryLabelOverrides[f.key] || f.label, color: colorForCat(f.key), group: "action" as const })),
      ...extraCategories.map((cat) => ({
        key: cat,
        label: categoryLabelOverrides[cat] || cat.replace(/_/g, " "),
        color: colorForCat(cat),
        group: "action" as const,
      })),
      ...agents.map((a) => ({ key: `agent:${a}`, label: a.replace(/_/g, " "), color: AGENT_NEUTRAL, group: "agent" as const })),
      { key: "state", label: categoryLabelOverrides.state || "System", color: colorForCat("state"), group: "system" as const },
    ],
    [agents, extraCategories, categoryLabelOverrides, colorForCat],
  );

  const [visible, setVisible] = useState<Record<string, boolean>>(() => {
    const v: Record<string, boolean> = { other: true };
    for (const f of ACTION_FILTERS) v[f.key] = f.on;
    for (const a of agents) v[`agent:${a}`] = true;
    v.state = false;
    return v;
  });
  const toggleFilter = useCallback((key: string) => {
    setVisible((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const visibleEvents = useMemo(
    () => classified.filter((e) => e._c.filterKeys.every((k) => visible[k] !== false)),
    [classified, visible],
  );

  // ── playhead + playback ──────────────────────────────────────────
  const [currentT, setCurrentT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const videoRef = useRef<HTMLVideoElement>(null);
  const videoMode = !!payload.video;
  const [activeVideo, setActiveVideo] = useState<ReplayVideo | null>(payload.video);

  const indexAt = useCallback(
    (t_ms: number): number => {
      let lo = 0;
      let hi = classified.length - 1;
      let best = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (classified[mid].t_ms <= t_ms) {
          best = mid;
          lo = mid + 1;
        } else hi = mid - 1;
      }
      return best;
    },
    [classified],
  );

  const snapshotAt = useCallback(
    (idx: number): { state: Record<string, unknown> | null; at: number | null } => {
      for (let i = idx; i >= 0; i--) {
        const si = classified[i].snapshot_index;
        if (si !== undefined) return { state: payload.snapshots[si] ?? null, at: classified[i].t_ms };
      }
      return { state: null, at: null };
    },
    [classified, payload.snapshots],
  );

  const cursorsAt = useCallback(
    (idx: number): Record<string, ReplayCursor> | null => {
      for (let i = idx; i >= 0; i--) {
        if (classified[i].type === "cursor_update" && classified[i].cursors) return classified[i].cursors!;
      }
      return null;
    },
    [classified],
  );

  const taskAt = useCallback(
    (idx: number): string | null => {
      for (let i = idx; i >= 0; i--) {
        if (classified[i].type === "task_end" && classified[i].task_id) return null;
        if (classified[i].type === "task_start" && classified[i].task_id) return classified[i].task_id;
      }
      return null;
    },
    [classified],
  );

  const lastPushedSnapshotAt = useRef(-1);
  const pushStateRef = useRef<((state: Record<string, unknown>) => void) | null>(null);

  
  const sessionToVideo = useCallback(
    (t_ms: number): number => {
      if (!activeVideo) return 0;
      const segs = activeVideo.segments;
      if (!segs || segs.length === 0) return (t_ms - activeVideo.start_t_ms) / 1000;
      if (t_ms <= segs[0].t_ms) return 0;
      for (let i = 0; i < segs.length; i++) {
        const s = segs[i];
        const end = s.t_ms + s.dur_ms;
        if (t_ms < end) return (s.video_t_ms + (t_ms - s.t_ms)) / 1000;
        
        const next = segs[i + 1];
        if (next && t_ms < next.t_ms) return (s.video_t_ms + s.dur_ms) / 1000;
      }
      const last = segs[segs.length - 1];
      return (last.video_t_ms + last.dur_ms) / 1000;
    },
    [activeVideo],
  );

  const videoToSession = useCallback(
    (videoSeconds: number): number => {
      if (!activeVideo) return 0;
      const segs = activeVideo.segments;
      const vt = videoSeconds * 1000;
      if (!segs || segs.length === 0) return activeVideo.start_t_ms + vt;
      for (let i = 0; i < segs.length; i++) {
        const s = segs[i];
        if (vt < s.video_t_ms + s.dur_ms) {
          return s.t_ms + Math.max(0, vt - s.video_t_ms);
        }
      }
      const last = segs[segs.length - 1];
      return last.t_ms + last.dur_ms;
    },
    [activeVideo],
  );

  const videoGaps = useMemo(() => {
    const segs = activeVideo?.segments;
    if (!segs || segs.length < 2) return [] as Array<{ t0: number; t1: number }>;
    const out: Array<{ t0: number; t1: number }> = [];
    for (let i = 0; i < segs.length - 1; i++) {
      const end = segs[i].t_ms + segs[i].dur_ms;
      const nextStart = segs[i + 1].t_ms;
      if (nextStart - end > 250) out.push({ t0: end, t1: nextStart });
    }
    return out;
  }, [activeVideo]);

  const seekVideo = useCallback(
    (t_ms: number) => {
      const video = videoRef.current;
      if (!videoMode || !video || !activeVideo) return;
      const vt = sessionToVideo(t_ms);
      if (vt >= 0 && isFinite(vt) && Math.abs((video.currentTime || 0) - vt) > 0.3) {
        try {
          video.currentTime = vt;
        } catch {
          // ignore
        }
      }
    },
    [videoMode, activeVideo, sessionToVideo],
  );

  const setT = useCallback(
    (t_ms: number, fromVideo = false) => {
      const clamped = Math.max(0, Math.min(t_ms, tMax));
      setCurrentT(clamped);
      const idx = indexAt(clamped);
      if (videoMode) {
        if (!fromVideo) seekVideo(clamped);
        return;
      }
      const { state, at } = snapshotAt(idx);
      if (state && at !== lastPushedSnapshotAt.current) {
        lastPushedSnapshotAt.current = at as number;
        pushStateRef.current?.(state);
      }
    },
    [tMax, indexAt, videoMode, seekVideo, snapshotAt],
  );

  const raf = useRef<number | null>(null);
  const lastWall = useRef(0);

  const pause = useCallback(() => {
    setPlaying(false);
    if (raf.current) cancelAnimationFrame(raf.current);
    if (videoMode && videoRef.current) {
      try {
        videoRef.current.pause();
      } catch {
        // ignore
      }
    }
  }, [videoMode]);

  const play = useCallback(() => {
    if (currentT >= tMax) setT(0);
    setPlaying(true);
    lastWall.current = 0;
    if (videoMode && videoRef.current) {
      videoRef.current.play().catch(() => {});
      return;
    }
  }, [currentT, tMax, setT, videoMode]);

  useEffect(() => {
    if (!playing || videoMode) return;
    let cancelled = false;
    const tick = (wall: number) => {
      if (cancelled) return;
      const dt = lastWall.current ? wall - lastWall.current : 16;
      lastWall.current = wall;
      setCurrentT((prev) => {
        const next = prev + dt * speed;
        if (next >= tMax) {
          setPlaying(false);
          return tMax;
        }
        return next;
      });
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      cancelled = true;
      if (raf.current) cancelAnimationFrame(raf.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, speed, videoMode, tMax]);

  useEffect(() => {
    if (videoMode) return;
    const idx = indexAt(currentT);
    const { state, at } = snapshotAt(idx);
    if (state && at !== lastPushedSnapshotAt.current) {
      lastPushedSnapshotAt.current = at as number;
      pushStateRef.current?.(state);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentT, videoMode]);

  const stepForward = useCallback(() => {
    const idx = indexAt(currentT);
    if (idx + 1 < classified.length) setT(classified[idx + 1].t_ms);
  }, [currentT, indexAt, classified, setT]);

  const stepBack = useCallback(() => {
    let idx = indexAt(currentT);
    if (idx >= 0 && classified[idx] && classified[idx].t_ms === currentT) idx -= 1;
    if (idx >= 0) setT(classified[idx].t_ms);
  }, [currentT, indexAt, classified, setT]);

  const jumpStart = useCallback(() => {
    setT(0);
    pause();
  }, [setT, pause]);

  useEffect(() => {
    const video = videoRef.current;
    if (!videoMode || !video) return;
    const onTimeUpdate = () => {
      if (!activeVideo) return;
      setT(videoToSession(video.currentTime), true);
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    video.addEventListener("timeupdate", onTimeUpdate);
    video.addEventListener("play", onPlay);
    video.addEventListener("pause", onPause);
    video.addEventListener("ended", onPause);
    video.playbackRate = speed;
    return () => {
      video.removeEventListener("timeupdate", onTimeUpdate);
      video.removeEventListener("play", onPlay);
      video.removeEventListener("pause", onPause);
      video.removeEventListener("ended", onPause);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoMode, activeVideo]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = speed;
  }, [speed]);

  return {
    sessionToVideo,
    videoToSession,
    videoGaps,
    classified,
    deltas,
    visibleEvents,
    lanes,
    laneIndex,
    laneOf,
    absentSpans,
    svgHeight,
    filters,
    visible,
    toggleFilter,
    currentT,
    tMax,
    playing,
    speed,
    setSpeed,
    setT,
    play,
    pause,
    stepForward,
    stepBack,
    jumpStart,
    indexAt,
    snapshotAt,
    cursorsAt,
    taskAt,
    videoMode,
    activeVideo,
    setActiveVideo,
    videoRef,
    pushStateRef,
    seekVideo,
  };
}

export type ReplayEngine = ReturnType<typeof useReplayEngine>;
