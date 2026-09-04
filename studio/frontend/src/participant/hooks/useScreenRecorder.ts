import { useCallback, useEffect, useRef, useState } from "react";

export type ScreenRecorderState = "idle" | "requesting" | "recording" | "stopped" | "error";

interface QueuedChunk {
  id?: number;
  blob: Blob;
  seq: number;
  recStart: string;
  chunkStart: string;
}

const DB_NAME = "studio-video-queue";
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
const queuePeek = (n = 4) =>
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

async function rawUpload(blob: Blob, seq: number, recStartIso: string, chunkStartIso: string): Promise<void> {
  const fd = new FormData();
  fd.append("chunk", blob, `chunk_${seq}.webm`);
  fd.append("seq", String(seq));
  fd.append("recorder_started_wall", recStartIso);
  fd.append("chunk_started_wall", chunkStartIso);
  const r = await fetch("/ingest/video-chunk", { method: "POST", body: fd });
  if (!r.ok) throw new Error(`ingest-failed-${r.status}`);
}

export function useScreenRecorder() {
  const [state, setState] = useState<ScreenRecorderState>("idle");
  const [error, setError] = useState<string | null>(null);
  const supported =
    typeof window !== "undefined" &&
    !!window.MediaRecorder &&
    !!navigator.mediaDevices?.getDisplayMedia &&
    !!navigator.mediaDevices?.getUserMedia;

  const displayStreamRef = useRef<MediaStream | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const seqRef = useRef(0);
  const finishedRef = useRef(false);
  const drainingRef = useRef(false);

  const drain = useCallback(async () => {
    if (drainingRef.current) return;
    drainingRef.current = true;
    try {
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const items = await queuePeek(4);
        if (!items.length) break;
        const it = items[0];
        try {
          await rawUpload(it.blob, it.seq, it.recStart, it.chunkStart);
          await queueDel(it.id!);
        } catch {
          break;
        }
      }
    } catch {
      // ignore
    }
    drainingRef.current = false;
  }, []);

  const stopRecorder = useCallback(() => {
    try {
      if (recorderRef.current && recorderRef.current.state !== "inactive") recorderRef.current.stop();
    } catch {
      // ignore
    }
    try {
      displayStreamRef.current?.getTracks().forEach((t) => t.stop());
    } catch {
      // ignore
    }
    try {
      micStreamRef.current?.getTracks().forEach((t) => t.stop());
    } catch {
      // ignore
    }
    setState("stopped");
  }, []);

  const flushAndFinish = useCallback(async () => {
    if (finishedRef.current) return;
    finishedRef.current = true;
    stopRecorder();
    const deadline = Date.now() + 8000;
    while (Date.now() < deadline) {
      await drain();
      const remaining = await queueCount().catch(() => 0);
      if (remaining === 0) break;
      await new Promise((r) => setTimeout(r, 400));
    }
    window.location.href = "/p/finish";
  }, [drain, stopRecorder]);

  const start = useCallback(async (withMic: boolean = true) => {
    setState("requesting");
    setError(null);
    try {
      const displayStream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 10 },
        audio: false,
        // Chrome-only hint; ignored elsewhere.
        preferCurrentTab: true,
      } as MediaStreamConstraints);
      displayStreamRef.current = displayStream;

      let micStream: MediaStream | null = null;
      if (withMic) {
        try {
          micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch {
          micStream = null; // continue video-only if the mic is blocked
        }
      }
      micStreamRef.current = micStream;

      const tracks = [...displayStream.getVideoTracks(), ...(micStream ? micStream.getAudioTracks() : [])];
      const combined = new MediaStream(tracks);
      const recorderStartedISO = new Date().toISOString();

      const mime = pickMime(["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"]);
      const recorder = new MediaRecorder(combined, mime ? { mimeType: mime, videoBitsPerSecond: 1_500_000 } : undefined);
      recorderRef.current = recorder;
      let chunkStartedISO = recorderStartedISO;

      recorder.addEventListener("dataavailable", async (e) => {
        const blob = e.data;
        const myStarted = chunkStartedISO;
        chunkStartedISO = new Date().toISOString();
        if (!blob || !blob.size) return;
        const mySeq = seqRef.current;
        seqRef.current += 1;
        try {
          await rawUpload(blob, mySeq, recorderStartedISO, myStarted);
          drain();
        } catch {
          await queuePush({ blob, seq: mySeq, recStart: recorderStartedISO, chunkStart: myStarted });
        }
      });
      recorder.addEventListener("error", () => setState("error"));

      displayStream.getVideoTracks()[0]?.addEventListener("ended", () => {
        if (!finishedRef.current) {
          setError("Screen sharing stopped — the rest of the session won't be recorded.");
          stopRecorder();
        }
      });

      recorder.start(CHUNK_MS);
      setState("recording");
      window.addEventListener("online", drain);
      window.setInterval(drain, 15000);
    } catch (err) {
      setError("Couldn't start recording. Make sure you allow screen sharing and pick THIS tab, then retry.");
      setState("idle");
      throw err;
    }
  }, [drain, stopRecorder]);

  useEffect(() => {
    const messageHandler = (e: MessageEvent) => {
      if (e.data === "studio:session_finished") flushAndFinish();
    };
    window.addEventListener("message", messageHandler);

    // Fallback: poll for finished state in case the message is missed.
    const pollTimer = window.setInterval(async () => {
      if (finishedRef.current || !recorderRef.current) return;
      try {
        const r = await fetch("/api/p/state");
        if (r.ok) {
          const s = await r.json();
          if (s.participant_status === "finished") flushAndFinish();
        }
      } catch {
        // ignore
      }
    }, 5000);

    drain(); 

    return () => {
      window.removeEventListener("message", messageHandler);
      window.clearInterval(pollTimer);
    };
  }, [drain, flushAndFinish]);

  return { state, error, supported, start };
}
