// MIVAIS Studio — participant-side audio capture 
//
// Active on task pages when the study has recording.audio != "none".
//   1. Asks for the microphone, runs MediaRecorder at ~5 s chunks.
//   2. POSTs each chunk to /ingest/audio-chunk with the chunk's wall-clock
//      start time. Server normalises everything to session-relative ms
//      using session.va_started_at + session.va_jsonl_offset_ms.
//   3. Persists chunks that fail to upload in IndexedDB ("studio-audio-queue")
//      so they survive page reloads and brief network outages.
//   4. Drains the queue in order whenever a fresh upload succeeds, when the
//      page regains connectivity, or every 15 s as a safety pulse.
//
// One recorder per page load. seq counts from 0 on each fresh start — the
// server tags chunks with wall clock, so the merged timeline stays coherent
// across refreshes.

(function () {
  const cfg = window.STUDIO_AUDIO;
  if (!cfg || cfg.mode === "none") return;

  const indicator = makeIndicator();
  document.body.appendChild(indicator.el);

  if (!window.MediaRecorder || !navigator.mediaDevices?.getUserMedia) {
    indicator.setState("unsupported", "Audio not supported by this browser");
    return;
  }

  let stream = null;
  let recorder = null;
  let seq = 0;
  let recorderStartedISO = null;
  let queuedCount = 0;
  const chunkMs = 5000;

  // ── IndexedDB queue ────────────────────────────────────────────────────
  const DB_NAME = "studio-audio-queue";
  const STORE = "chunks";
  const openDB = () => new Promise((res, rej) => {
    const r = indexedDB.open(DB_NAME, 1);
    r.onupgradeneeded = () => {
      r.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
    };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
  const dbTx = async (mode, fn) => {
    const db = await openDB();
    return new Promise((res, rej) => {
      const tx = db.transaction(STORE, mode);
      tx.oncomplete = () => res(out);
      tx.onerror = () => rej(tx.error);
      let out;
      Promise.resolve(fn(tx.objectStore(STORE))).then(v => (out = v));
    });
  };
  const queuePush = (item) => dbTx("readwrite", (s) => new Promise((res) => {
    const r = s.add(item);
    r.onsuccess = () => res(r.result);
  }));
  const queuePeek = (n = 8) => dbTx("readonly", (s) => new Promise((res) => {
    const out = [];
    const req = s.openCursor();
    req.onsuccess = (e) => {
      const cur = e.target.result;
      if (cur && out.length < n) { out.push(cur.value); cur.continue(); }
      else res(out);
    };
  }));
  const queueDel = (id) => dbTx("readwrite", (s) => new Promise((res) => {
    const r = s.delete(id); r.onsuccess = () => res(true);
  }));
  const queueCount = () => dbTx("readonly", (s) => new Promise((res) => {
    const r = s.count(); r.onsuccess = () => res(r.result || 0);
  }));

  const refreshQueueIndicator = async () => {
    try {
      queuedCount = await queueCount();
      const lbl = indicator.el.querySelector(".audio-label");
      const stateAttr = indicator.el.dataset.state;
      if (queuedCount > 0 && stateAttr === "recording") {
        lbl.textContent = `Recording · ${queuedCount} queued`;
      }
    } catch {}
  };

  // Drain the IDB queue oldest-first. Stops at the first failure so order
  // is preserved.
  let draining = false;
  const drain = async () => {
    if (draining) return;
    draining = true;
    try {
      while (true) {
        const items = await queuePeek(8);
        if (!items.length) break;
        const item = items[0];
        try {
          await rawUpload(item.blob, item.seq, item.recStart, item.chunkStart);
          await queueDel(item.id);
        } catch {
          break; // bail; try again next tick
        }
      }
    } catch {}
    draining = false;
    refreshQueueIndicator();
  };

  start().catch((err) => {
    console.error("audio: getUserMedia failed", err);
    indicator.setState("denied", "Microphone blocked");
  });

  async function start() {
    indicator.setState("requesting", "Requesting microphone…");
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recorderStartedISO = new Date().toISOString();

    const mime = pickMime();
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 32000 } : undefined);
    let chunkStartedISO = recorderStartedISO;
    let nextStartedISO = recorderStartedISO;

    recorder.addEventListener("dataavailable", async (e) => {
      const blob = e.data;
      const myStarted = chunkStartedISO;
      chunkStartedISO = nextStartedISO;
      nextStartedISO = new Date().toISOString();
      if (!blob || !blob.size) return;
      const mySeq = seq; seq += 1;
      try {
        await rawUpload(blob, mySeq, recorderStartedISO, myStarted);
        // Opportunistically drain anything that was queued earlier.
        drain();
      } catch (err) {
        // Persist to IDB and keep recording. We never drop audio silently.
        await queuePush({
          blob, seq: mySeq, recStart: recorderStartedISO, chunkStart: myStarted,
        });
        refreshQueueIndicator();
      }
    });

    recorder.addEventListener("error", (e) => {
      console.error("audio: recorder error", e);
      indicator.setState("error", "Recorder error");
    });

    recorder.start(chunkMs);
    indicator.setState("recording", "Recording");
    refreshQueueIndicator();

    window.addEventListener("online", drain);
    setInterval(drain, 15000); // safety pulse

    window.addEventListener("beforeunload", () => {
      try { recorder?.stop(); } catch {}
      try { stream?.getTracks().forEach((t) => t.stop()); } catch {}
    });
  }

  function pickMime() {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
    ];
    for (const c of candidates) {
      if (window.MediaRecorder.isTypeSupported(c)) return c;
    }
    return null;
  }

  async function rawUpload(blob, seqNum, recorderStartedIso, chunkStartedIso) {
    const fd = new FormData();
    fd.append("chunk", blob, `chunk_${seqNum}.webm`);
    fd.append("seq", String(seqNum));
    fd.append("recorder_started_wall", recorderStartedIso);
    fd.append("chunk_started_wall", chunkStartedIso);
    const r = await fetch("/ingest/audio-chunk", { method: "POST", body: fd });
    if (!r.ok) throw new Error("ingest-failed-" + r.status);
  }

  function makeIndicator() {
    const el = document.createElement("div");
    el.className = "audio-indicator";
    el.innerHTML = `<span class="audio-dot"></span><span class="audio-label">…</span>`;
    return {
      el,
      setState(state, label) {
        el.dataset.state = state;
        const lbl = el.querySelector(".audio-label");
        if (lbl) lbl.textContent = label;
      },
    };
  }

  drain();
})();
