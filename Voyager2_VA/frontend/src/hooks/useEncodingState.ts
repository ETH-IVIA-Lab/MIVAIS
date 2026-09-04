import { useCallback, useEffect, useRef, useState } from "react";
import { CHANNELS } from "../types";
import type { EncodingEntry, ShelfEntry } from "../types";

export interface EncodingState {
  mark: string;
  shelves: Record<string, ShelfEntry | null>;
  anyFields: ShelfEntry[];
}

const EMPTY_SHELVES: Record<string, ShelfEntry | null> = Object.fromEntries(CHANNELS.map((c) => [c, null]));
const EMPTY_STATE: EncodingState = { mark: "auto", shelves: EMPTY_SHELVES, anyFields: [] };

function encodingOf(s: ShelfEntry, channel?: string): EncodingEntry {
  const enc: EncodingEntry = { channel, field: s.field, type: s.type };
  if (s.aggregate && s.aggregate !== "none") enc.aggregate = s.aggregate;
  if (s.bin) enc.bin = true;
  if (s.timeUnit) enc.timeUnit = s.timeUnit;
  return enc;
}

export function stateToSpec(s: EncodingState): { mark: string; encodings: EncodingEntry[] } {
  const encodings: EncodingEntry[] = [];
  CHANNELS.forEach((ch) => {
    const entry = s.shelves[ch];
    if (entry) encodings.push(encodingOf(entry, ch));
  });
  s.anyFields.forEach((entry) => encodings.push(encodingOf(entry)));
  return { mark: s.mark, encodings };
}

export function specToState(spec: { mark?: string; encodings?: EncodingEntry[] } | undefined | null): EncodingState {
  const shelves: Record<string, ShelfEntry | null> = { ...EMPTY_SHELVES };
  const anyFields: ShelfEntry[] = [];
  (spec?.encodings ?? []).forEach((enc) => {
    const entry: ShelfEntry = {
      field: enc.field,
      type: enc.type,
      aggregate: enc.aggregate || "none",
      bin: !!enc.bin,
      timeUnit: enc.timeUnit || "",
    };
    if (enc.channel && (CHANNELS as readonly string[]).includes(enc.channel)) shelves[enc.channel] = entry;
    else anyFields.push(entry);
  });
  return { mark: spec?.mark || "auto", shelves, anyFields };
}

const PREFERRED_BY_ABBR: Record<string, string[]> = {
  Q: ["y", "x", "size", "color"],
  T: ["x", "y", "color"],
  N: ["color", "x", "y", "shape", "row", "column"],
  O: ["color", "x", "y", "shape", "row", "column"],
};


export function useEncodingState(sendUpdateSpec: (spec: { mark: string; encodings: EncodingEntry[] }) => void) {
  const [state, setState] = useState<EncodingState>(EMPTY_STATE);
  const stateRef = useRef(state);
  const undoStack = useRef<string[]>([]);
  const redoStack = useRef<string[]>([]);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  const pendingSent = useRef<string[]>([]);

  const syncFlags = useCallback(() => {
    setCanUndo(undoStack.current.length > 0);
    setCanRedo(redoStack.current.length > 0);
  }, []);

  const pushUndo = useCallback(() => {
    undoStack.current.push(JSON.stringify(stateToSpec(stateRef.current)));
    if (undoStack.current.length > 50) undoStack.current.shift();
    redoStack.current = [];
    syncFlags();
  }, [syncFlags]);

  const applyLocal = useCallback(
    (updater: (prev: EncodingState) => EncodingState, opts?: { sync?: boolean }) => {
      const next = updater(stateRef.current);
      stateRef.current = next;
      setState(next);
      if (opts?.sync ?? true) {
        const spec = stateToSpec(next);
        pendingSent.current.push(JSON.stringify(spec));
        if (pendingSent.current.length > 20) pendingSent.current.shift();
        sendUpdateSpec(spec);
      }
    },
    [sendUpdateSpec],
  );

  const setMark = useCallback(
    (mark: string) => {
      pushUndo();
      applyLocal((prev) => ({ ...prev, mark }));
    },
    [pushUndo, applyLocal],
  );

  const dropField = useCallback(
    (channel: string, entry: ShelfEntry) => {
      pushUndo();
      applyLocal((prev) =>
        channel === "any"
          ? { ...prev, anyFields: [...prev.anyFields, entry] }
          : { ...prev, shelves: { ...prev.shelves, [channel]: entry } },
      );
    },
    [pushUndo, applyLocal],
  );

  const removeChannel = useCallback(
    (channel: string) => {
      pushUndo();
      applyLocal((prev) => ({ ...prev, shelves: { ...prev.shelves, [channel]: null } }));
    },
    [pushUndo, applyLocal],
  );

  const removeAnyField = useCallback(
    (idx: number) => {
      pushUndo();
      applyLocal((prev) => ({ ...prev, anyFields: prev.anyFields.filter((_, i) => i !== idx) }));
    },
    [pushUndo, applyLocal],
  );

  const updateEntry = useCallback(
    (target: { channel: string } | { anyIdx: number }, patch: Partial<ShelfEntry>) => {
      pushUndo();
      applyLocal((prev) => {
        if ("channel" in target) {
          const cur = prev.shelves[target.channel];
          if (!cur) return prev;
          return { ...prev, shelves: { ...prev.shelves, [target.channel]: { ...cur, ...patch } } };
        }
        const cur = prev.anyFields[target.anyIdx];
        if (!cur) return prev;
        const anyFields = [...prev.anyFields];
        anyFields[target.anyIdx] = { ...cur, ...patch };
        return { ...prev, anyFields };
      });
    },
    [pushUndo, applyLocal],
  );

  const autoAssignField = useCallback(
    (field: string, type: string, abbr: string) => {
      pushUndo();
      const entry: ShelfEntry = { field, type, aggregate: field === "*" ? "count" : "none", bin: false, timeUnit: "" };
      const preferred = PREFERRED_BY_ABBR[abbr] || PREFERRED_BY_ABBR.N;
      applyLocal((prev) => {
        for (const ch of preferred) {
          if (!prev.shelves[ch]) return { ...prev, shelves: { ...prev.shelves, [ch]: entry } };
        }
        return { ...prev, anyFields: [...prev.anyFields, entry] };
      });
    },
    [pushUndo, applyLocal],
  );

  
  const applySpec = useCallback(
    (spec: { mark?: string; encodings?: EncodingEntry[] }, opts?: { sync?: boolean }) => {
      applyLocal(() => specToState(spec), opts);
    },
    [applyLocal],
  );

  
  const doUndo = useCallback(() => {
    if (!undoStack.current.length) return;
    redoStack.current.push(JSON.stringify(stateToSpec(stateRef.current)));
    const prevSpec = JSON.parse(undoStack.current.pop()!);
    applySpec(prevSpec);
    syncFlags();
  }, [applySpec, syncFlags]);

  const doRedo = useCallback(() => {
    if (!redoStack.current.length) return;
    undoStack.current.push(JSON.stringify(stateToSpec(stateRef.current)));
    const nextSpec = JSON.parse(redoStack.current.pop()!);
    applySpec(nextSpec);
    syncFlags();
  }, [applySpec, syncFlags]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        doUndo();
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === "y" || (e.key === "z" && e.shiftKey))) {
        e.preventDefault();
        doRedo();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [doUndo, doRedo]);

  
  const syncFromServerSpec = useCallback(
    (spec: { mark?: string; encodings?: EncodingEntry[] } | undefined) => {
      if (!spec) return;
      const incoming = JSON.stringify({ mark: spec.mark || "auto", encodings: spec.encodings ?? [] });
      const pendIdx = pendingSent.current.indexOf(incoming);
      if (pendIdx >= 0) {
        // our own echo — consume it (and anything older) and keep local state
        pendingSent.current = pendingSent.current.slice(pendIdx + 1);
        return;
      }
      if (incoming === JSON.stringify(stateToSpec(stateRef.current))) return;
      applySpec(spec, { sync: false });
    },
    [applySpec],
  );

  return {
    mark: state.mark,
    shelves: state.shelves,
    anyFields: state.anyFields,
    canUndo,
    canRedo,
    setMark,
    dropField,
    removeChannel,
    removeAnyField,
    updateEntry,
    autoAssignField,
    doUndo,
    doRedo,
    syncFromServerSpec,
  };
}
