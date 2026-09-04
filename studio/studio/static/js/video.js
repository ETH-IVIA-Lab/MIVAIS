// MIVAIS Studio — participant-side screen+mic recorder (recorder shell).
//
// Runs on /p/run, the single long-lived page that hosts the whole session in a
// nested iframe. getDisplayMedia needs a user gesture and cannot silently
// re-acquire across page loads, so we capture ONCE here and let the inner iframe
// navigate freely without losing the stream.
//
//   1. On the Start click: capture the current tab (video) + mic (audio),
//      combine into one MediaStream, MediaRecorder at ~5 s chunks.
//   2. POST each chunk to /ingest/video-chunk with wall-clock timing; the server
//      normalises to session-relative ms so it lines up with events.
//   3. IndexedDB queue ("studio-video-queue") survives brief network outages.
//   4. When the inner iframe signals 'studio:session_finished' (or /p/state says
//      finished), stop + flush the queue, then navigate the top window to /p/finish.

(function () {
  const cfg = window.STUDIO_VIDEO;
  if (!cfg) return;

  const startBtn  = document.getElementById("rec-start");
  const innerWrap = document.getElementById("inner-wrap");
  const innerFrame = document.getElementById("studio-inner");
  const overlay   = document.getElementById("rec-overlay");
  const indicator = document.getElementById("rec-indicator");
  const errBox    = document.getElementById("rec-error");

  const setIndicator = (state, label) => {
    if (!indicator) return;
    indicator.dataset.state = state;
    const lbl = indicator.querySelector(".rec-label");
    if (lbl) lbl.textContent = label;
  };
  const showError = (msg) => { if (errBox) { errBox.textContent = msg; errBox.style.display = "block"; } };

  if (!window.MediaRecorder || !navigator.mediaDevices?.getDisplayMedia || !navigator.mediaDevices?.getUserMedia) {
    showError("This browser can't screen-record. Please use a recent Chrome, Edge, or Firefox on a computer.");
    if (startBtn) startBtn.disabled = true;
    return;
  }

  let displayStream = null, micStream = null, recorder = null;
  let seq = 0, recorderStartedISO = null, finished = false, draining = false;
  const chunkMs = 5000;

  // ── IndexedDB offline queue (mirrors audio.js) ─────────────────────────────
  const DB_NAME = "studio-video-queue", STORE = "chunks";
  const openDB = () => new Promise((res, rej) => {
    const r = indexedDB.open(DB_NAME, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
  const dbTx = async (mode, fn) => {
    const db = await openDB();
    return new Promise((res, rej) => {
      const tx = db.transaction(STORE, mode);
      let out;
      tx.oncomplete = () => res(out);
      tx.onerror = () => rej(tx.error);
      Promise.resolve(fn(tx.objectStore(STORE))).then((v) => (out = v));
    });
  };
  const queuePush = (item) => dbTx("readwrite", (s) => new Promise((res) => { const r = s.add(item); r.onsuccess = () => res(r.result); }));
  const queuePeek = (n = 4) => dbTx("readonly", (s) => new Promise((res) => {
    const out = []; const req = s.openCursor();
    req.onsuccess = (e) => { const cur = e.target.result; if (cur && out.length < n) { out.push(cur.value); cur.continue(); } else res(out); };
  }));
  const queueDel = (id) => dbTx("readwrite", (s) => new Promise((res) => { const r = s.delete(id); r.onsuccess = () => res(true); }));
  const queueCount = () => dbTx("readonly", (s) => new Promise((res) => { const r = s.count(); r.onsuccess = () => res(r.result || 0); }));

  const drain = async () => {
    if (draining) return;
    draining = true;
    try {
      while (true) {
        const items = await queuePeek(4);
        if (!items.length) break;
        const it = items[0];
        try { await rawUpload(it.blob, it.seq, it.recStart, it.chunkStart); await queueDel(it.id); }
        catch { break; }
      }
    } catch {} finally { draining = false; }
  };

  async function rawUpload(blob, seqNum, recStartIso, chunkStartIso) {
    const fd = new FormData();
    fd.append("chunk", blob, `chunk_${seqNum}.webm`);
    fd.append("seq", String(seqNum));
    fd.append("recorder_started_wall", recStartIso);
    fd.append("chunk_started_wall", chunkStartIso);
    const r = await fetch("/ingest/video-chunk", { method: "POST", body: fd });
    if (!r.ok) throw new Error("ingest-failed-" + r.status);
  }

  function pickMime() {
    const candidates = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"];
    for (const c of candidates) if (window.MediaRecorder.isTypeSupported(c)) return c;
    return null;
  }

  // ── Capture + record ───────────────────────────────────────────────────────
  async function startCapture() {
    setIndicator("requesting", "Requesting screen + mic…");
    // Tab capture (incl. the embedded VA). preferCurrentTab is a Chrome hint.
    displayStream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: 10 }, audio: false, preferCurrentTab: true,
    });
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      micStream = null; // continue video-only if the mic is blocked
    }

    const tracks = [...displayStream.getVideoTracks(), ...(micStream ? micStream.getAudioTracks() : [])];
    const combined = new MediaStream(tracks);
    recorderStartedISO = new Date().toISOString();

    const mime = pickMime();
    recorder = new MediaRecorder(combined, mime ? { mimeType: mime, videoBitsPerSecond: 1_500_000 } : undefined);
    // Each chunk's wall-clock start = the moment the previous chunk ended.
    let chunkStartedISO = recorderStartedISO;

    recorder.addEventListener("dataavailable", async (e) => {
      const blob = e.data;
      const myStarted = chunkStartedISO;
      chunkStartedISO = new Date().toISOString();  // next chunk starts now
      if (!blob || !blob.size) return;
      const mySeq = seq; seq += 1;
      try { await rawUpload(blob, mySeq, recorderStartedISO, myStarted); drain(); }
      catch { await queuePush({ blob, seq: mySeq, recStart: recorderStartedISO, chunkStart: myStarted }); }
    });
    recorder.addEventListener("error", () => setIndicator("error", "Recorder error"));

    
    displayStream.getVideoTracks()[0]?.addEventListener("ended", () => {
      if (!finished) { showError("Screen sharing stopped — the rest of the session won't be recorded."); stopRecorder(); }
    });

    recorder.start(chunkMs);
    setIndicator("recording", "Recording");
    window.addEventListener("online", drain);
    setInterval(drain, 15000);
  }

  function stopRecorder() {
    try { recorder?.state !== "inactive" && recorder?.stop(); } catch {}
    try { displayStream?.getTracks().forEach((t) => t.stop()); } catch {}
    try { micStream?.getTracks().forEach((t) => t.stop()); } catch {}
    setIndicator("stopped", "Recording stopped");
  }

  // Wait until the IDB queue is empty (or a timeout) so we don't drop tail chunks.
  async function flushAndFinish() {
    if (finished) return; finished = true;
    stopRecorder();
    const deadline = Date.now() + 8000;
    while (Date.now() < deadline) {
      await drain();
      if ((await queueCount().catch(() => 0)) === 0) break;
      await new Promise((r) => setTimeout(r, 400));
    }
    window.location.href = "/p/finish";
  }

  // ── Wiring ──────────────────────────────────────────────────────────────────
  startBtn?.addEventListener("click", async () => {
    startBtn.disabled = true;
    try {
      await startCapture();
      if (overlay) overlay.style.display = "none";
      if (innerWrap) innerWrap.style.display = "block";
      if (innerFrame) innerFrame.src = cfg.start || "/p/resume";
    } catch (err) {
      console.error("video: capture failed", err);
      showError("Couldn't start recording. Make sure you allow screen sharing and pick THIS tab, then retry.");
      startBtn.disabled = false;
    }
  });

  // Inner iframe tells us the participant reached the end.
  window.addEventListener("message", (e) => {
    if (e && e.data === "studio:session_finished") flushAndFinish();
  });

  // Fallback: poll for finished state in case the message is missed.
  setInterval(async () => {
    if (finished || !recorder) return;
    try {
      const r = await fetch("/p/state");
      if (r.ok) { const s = await r.json(); if (s.participant_status === "finished") flushAndFinish(); }
    } catch {}
  }, 5000);

  // Drain anything left from a previous shell load.
  drain();
})();
