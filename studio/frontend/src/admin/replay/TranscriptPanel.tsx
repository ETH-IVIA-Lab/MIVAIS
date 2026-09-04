import { useEffect, useRef, useState } from "react";
import type { ReplayVideo } from "./types";

interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

interface MarkPopover {
  x: number;
  y: number;
  t_ms: number;
  quote: string;
}

interface TranscriptResponse {
  status: "ready" | "transcribing" | "disabled" | "none";
  segments: TranscriptSegment[];
}

function fmtT(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(2)}s`;
}


export function TranscriptPanel({
  sessionId,
  video,
  videoEl,
  onSeek,
  onMarkText,
}: {
  sessionId: string;
  video: ReplayVideo;
  videoEl: HTMLVideoElement | null;
  onSeek: (seconds: number) => void;
  /** Mint a marker from a text selection: timeline time + the selected text. */
  onMarkText?: (t_ms: number, quote: string) => void;
}) {
  const [status, setStatus] = useState<TranscriptResponse["status"]>("none");
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [activeIdx, setActiveIdx] = useState(-1);
  const [popover, setPopover] = useState<MarkPopover | null>(null);
  const pollTimer = useRef<number | null>(null);
  const listRef = useRef<HTMLOListElement>(null);

  
  function onListMouseUp() {
    if (!onMarkText) return;
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) {
      setPopover(null);
      return;
    }
    const quote = sel.toString().replace(/\s+/g, " ").trim();
    if (!quote) {
      setPopover(null);
      return;
    }
    const range = sel.getRangeAt(0);
    const node = range.startContainer;
    const li = (node instanceof Element ? node : node.parentElement)?.closest("li[data-seg-idx]");
    if (!li || !listRef.current?.contains(li)) {
      setPopover(null);
      return;
    }
    const idx = Number(li.getAttribute("data-seg-idx"));
    const seg = segments[idx];
    if (!seg) {
      setPopover(null);
      return;
    }
    const rect = range.getBoundingClientRect();
    setPopover({
      x: rect.left + rect.width / 2,
      y: rect.top,
      t_ms: Math.max(0, Math.round(seg.start * 1000 + video.start_t_ms)),
      quote: quote.slice(0, 500),
    });
  }

  useEffect(() => {
    
    setStatus("none");
    setSegments([]);
    setActiveIdx(-1);
    if (!video.transcribe) return;
    let cancelled = false;
    const runQ = video.run_id ? `?run=${encodeURIComponent(video.run_id)}` : "";
    const poll = async () => {
      try {
        const r = await fetch(`/admin/sessions/${sessionId}/transcript${runQ}`);
        if (!r.ok) return;
        const d: TranscriptResponse = await r.json();
        if (cancelled) return;
        setStatus(d.status);
        if (d.status === "ready") {
          setSegments(d.segments);
          return;
        }
      } catch {
        // transient
      }
      if (!cancelled) pollTimer.current = window.setTimeout(poll, 4000);
    };
    poll();
    return () => {
      cancelled = true;
      if (pollTimer.current) window.clearTimeout(pollTimer.current);
    };
  }, [sessionId, video]);

  useEffect(() => {
    
    if (!videoEl) return;
    Array.from(videoEl.querySelectorAll("track")).forEach((t) => t.remove());
    
    if (status !== "ready") return;
    const track = document.createElement("track");
    track.kind = "subtitles";
    track.label = "Transcript";
    track.srclang = "en";
    track.default = true;
    const runQ = video.run_id ? `?run=${encodeURIComponent(video.run_id)}` : "";
    track.src = `/admin/sessions/${sessionId}/subtitles.vtt${runQ}`;
    videoEl.appendChild(track);
    const t = window.setTimeout(() => {
      try {
        if (videoEl.textTracks[0]) videoEl.textTracks[0].mode = "showing";
      } catch {
        // ignore
      }
    }, 250);
    return () => window.clearTimeout(t);
  }, [videoEl, status, sessionId, video]);

  useEffect(() => {
    if (!videoEl || !segments.length) return;
    const onTimeUpdate = () => {
      const t = videoEl.currentTime;
      let idx = -1;
      for (let i = 0; i < segments.length; i++) {
        if (segments[i].start <= t) idx = i;
        else break;
      }
      setActiveIdx(idx);
    };
    videoEl.addEventListener("timeupdate", onTimeUpdate);
    return () => videoEl.removeEventListener("timeupdate", onTimeUpdate);
  }, [videoEl, segments]);

  if (!video.transcribe) return null;

  return (
    <div className="transcript-panel">
      <header className="replay-section-head">
        <h2>Transcript</h2>
        <span className="muted small">
          {status === "ready" ? `${segments.length} segment(s)` : status === "transcribing" ? "transcribing… (can take a minute)" : status === "disabled" ? "transcription off" : "no transcript"}
        </span>
      </header>
      <ol className="transcript-list" ref={listRef} onMouseUp={onListMouseUp} onMouseDown={() => setPopover(null)}>
        {segments.map((s, i) => (
          <li
            key={i}
            data-seg-idx={i}
            className="transcript-line"
            title={`jump to ${s.start.toFixed(1)}s — select text to mark it`}
            style={{ padding: "3px 6px", borderRadius: 6, cursor: "pointer", background: i === activeIdx ? "var(--accent-bg)" : "" }}
            onClick={() => {
              
              if (window.getSelection()?.isCollapsed !== false) onSeek(s.start);
            }}
          >
            <span className="mono small" style={{ color: "var(--ink-muted)", marginRight: 6 }}>
              {fmtT(Math.round(s.start * 1000))}
            </span>
            {s.text}
          </li>
        ))}
      </ol>
      {popover && onMarkText && (
        <button
          type="button"
          className="rp-mark-popover"
          style={{ position: "fixed", left: popover.x, top: popover.y }}
          
          onMouseDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onMarkText(popover.t_ms, popover.quote);
            setPopover(null);
            window.getSelection()?.removeAllRanges();
          }}
        >
          &#9873; Mark &middot; {fmtT(popover.t_ms)}
        </button>
      )}
    </div>
  );
}
