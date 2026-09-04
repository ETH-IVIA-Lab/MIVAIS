import { useEffect, useState, type MutableRefObject } from "react";
import { CursorOverlay } from "./CursorOverlay";
import { CameraIcon } from "./icons";
import type { ReplayPayload } from "./types";
import type { ReplayEngine } from "./useReplayEngine";
import type { ReplayVAStatus } from "./useReplayVA";

export function ReplayVaStage({
  payload,
  engine,
  vaStatus,
  vaIframeUrl,
  onVideoEl,
}: {
  payload: ReplayPayload;
  engine: ReplayEngine;
  vaStatus: ReplayVAStatus;
  vaIframeUrl: string | null;
  onVideoEl?: (el: HTMLVideoElement | null) => void;
}) {
  const { videoMode, activeVideo, setActiveVideo, videoRef, cursorsAt, indexAt, currentT, seekVideo, videoGaps } = engine;
  const inGap = videoMode && videoGaps.some((g) => currentT >= g.t0 && currentT < g.t1);
  const [videoNode, setVideoNode] = useState<HTMLVideoElement | null>(null);
  const cursors = !videoMode ? cursorsAt(indexAt(currentT)) : null;

  const setRefs = (el: HTMLVideoElement | null) => {
    (videoRef as MutableRefObject<HTMLVideoElement | null>).current = el;
    setVideoNode(el);
    onVideoEl?.(el);
  };

  useEffect(() => {
    const el = videoNode;
    if (!el || !activeVideo) return;
    const onLoaded = () => seekVideo(currentT);
    el.addEventListener("loadedmetadata", onLoaded, { once: true });
    el.load();
    return () => el.removeEventListener("loadedmetadata", onLoaded);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeVideo?.run_id]);

  return (
    <section className="replay-va card">
      <header className="replay-section-head">
        <h2>Participant POV</h2>
        <span className="muted small">
          {videoMode ? (
            activeVideo ? (
              <>
                <CameraIcon /> watching · {activeVideo.label}
              </>
            ) : (
              "recording"
            )
          ) : (
            vaStatus
          )}
        </span>
        {inGap && (
          <span
            className="chip warn"
            style={{ marginLeft: 8 }}
            title="No video chunk covers this moment — the recording has a gap here. The timeline is still accurate."
          >
            no footage here
          </span>
        )}
        {videoMode && payload.videos.length > 1 && (
          <select
            id="pov-select"
            style={{ marginLeft: "auto" }}
            value={activeVideo?.run_id}
            onChange={(e) => {
              const v = payload.videos.find((x) => x.run_id === e.target.value);
              if (v) setActiveVideo(v);
            }}
          >
            {payload.videos.map((v) => (
              <option key={v.run_id} value={v.run_id}>
                POV · {v.label}
              </option>
            ))}
          </select>
        )}
      </header>
      <div className="replay-va-stage" id="va-stage">
        {videoMode ? (
          <video ref={setRefs} playsInline crossOrigin="use-credentials" style={{ width: "100%", height: "100%", background: "#000" }} src={activeVideo?.src} />
        ) : (
          <>
            <iframe title="Replay VA" allow="fullscreen" src={vaIframeUrl ?? undefined} style={{ width: "100%", height: "100%", border: 0 }} />
            <CursorOverlay cursors={cursors} />
          </>
        )}
      </div>
    </section>
  );
}
