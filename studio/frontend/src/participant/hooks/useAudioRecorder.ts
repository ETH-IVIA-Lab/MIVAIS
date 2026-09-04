import { useEffect, useState } from "react";

export type AudioIndicatorState = "idle" | "requesting" | "recording" | "denied" | "unsupported" | "error";

interface QueuedChunk {
  id?: number;
  blob: Blob;
  seq: number;
  recStart: string;
  chunkStart: string;
}

const DB_NAME = "studio-audio-queue";
const STORE = "chunks";
const CHUNK_MS = 5000;

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB_NAME, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

async function dbTx<T>(mode: IDBTransactionMode, fn: (store: IDBObjectStore) => Promise<T>): Promise<T> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    let out: T;
    tx.oncomplete = () => resolve(out);
    tx.onerror = () => reject(tx.error);
    Promise.resolve(fn(tx.objectStore(STORE))).then((v) => (out = v));
  });
}

const queuePush = (item: QueuedChunk) =>
  dbTx<number>("readwrite", (s) => new Promise((res) => {
    const r = s.add(item);
    r.onsuccess = () => res(r.result as number);
  }));
const queuePeek = (n = 8) =>
  dbTx<QueuedChunk[]>("readonly", (s) => new Promise((res) => {
    const out: QueuedChunk[] = [];
    const req = s.openCursor();
    req.onsuccess = (e) => {
      const cur = (e.target as IDBRequest<IDBCursorWithValue | null>).result;
      if (cur && out.length < n) {
        out.push(cur.value);
        cur.continue();
      } else res(out);
    };
  }));
const queueDel = (id: number) =>
  dbTx<boolean>("readwrite", (s) => new Promise((res) => {
    const r = s.delete(id);
    r.onsuccess = () => res(true);
  }));
const queueCount = () =>
  dbTx<number>("readonly", (s) => new Promise((res) => {
    const r = s.count();
    r.onsuccess = () => res(r.result || 0);
  }));

function pickMime(candidates: string[]): string | null {
  for (const c of candidates) {
    if (window.MediaRecorder.isTypeSupported(c)) return c;
  }
  return null;
}

async function rawUpload(blob: Blob, seq: number, recorderStartedIso: string, chunkStartedIso: string): Promise<void> {
  const fd = new FormData();
  fd.append("chunk", blob, `chunk_${seq}.webm`);
  fd.append("seq", String(seq));
  fd.append("recorder_started_wall", recorderStartedIso);
  fd.append("chunk_started_wall", chunkStartedIso);
  const r = await fetch("/ingest/audio-chunk", { method: "POST", body: fd });
  if (!r.ok) throw new Error(`ingest-failed-${r.status}`);
}

export function useAudioRecorder(mode: string | undefined) {
  const [state, setState] = useState<AudioIndicatorState>("idle");
  const [queuedCount, setQueuedCount] = useState(0);

  useEffect(() => {
    if (!mode || mode === "none") return;
    if (!window.MediaRecorder || !navigator.mediaDevices?.getUserMedia) {
      setState("unsupported");
      return;
    }

    let stream: MediaStream | null = null;
    let recorder: MediaRecorder | null = null;
    let seq = 0;
    let recorderStartedISO = "";
    let chunkStartedISO = "";
    let nextStartedISO = "";
    let draining = false;
    let drainTimer: number | undefined;
    let cancelled = false;

    const refreshQueue = async () => {
      try {
        const n = await queueCount();
        if (!cancelled) setQueuedCount(n);
      } catch {
        // ignore
      }
    };

    const drain = async () => {
      if (draining) return;
      draining = true;
      try {
        // eslint-disable-next-line no-constant-condition
        while (true) {
          const items = await queuePeek(8);
          if (!items.length) break;
          const item = items[0];
          try {
            await rawUpload(item.blob, item.seq, item.recStart, item.chunkStart);
            await queueDel(item.id!);
          } catch {
            break; 
          }
        }
      } catch {
        // ignore
      }
      draining = false;
      refreshQueue();
    };

    const start = async () => {
      setState("requesting");
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recorderStartedISO = new Date().toISOString();
      chunkStartedISO = recorderStartedISO;
      nextStartedISO = recorderStartedISO;

      const mime = pickMime(["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"]);
      recorder = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 32000 } : undefined);

      recorder.addEventListener("dataavailable", async (e) => {
        const blob = e.data;
        const myStarted = chunkStartedISO;
        chunkStartedISO = nextStartedISO;
        nextStartedISO = new Date().toISOString();
        if (!blob || !blob.size) return;
        const mySeq = seq;
        seq += 1;
        try {
          await rawUpload(blob, mySeq, recorderStartedISO, myStarted);
          drain();
        } catch {
          await queuePush({ blob, seq: mySeq, recStart: recorderStartedISO, chunkStart: myStarted });
          refreshQueue();
        }
      });

      recorder.addEventListener("error", () => setState("error"));

      recorder.start(CHUNK_MS);
      setState("recording");
      refreshQueue();

      window.addEventListener("online", drain);
      drainTimer = window.setInterval(drain, 15000);
    };

    start().catch(() => setState("denied"));
    drain(); 

    return () => {
      cancelled = true;
      window.removeEventListener("online", drain);
      if (drainTimer) window.clearInterval(drainTimer);
      try {
        recorder?.stop();
      } catch {
        // ignore
      }
      try {
        stream?.getTracks().forEach((t) => t.stop());
      } catch {
        // ignore
      }
    };
  }, [mode]);

  return { state, queuedCount };
}
