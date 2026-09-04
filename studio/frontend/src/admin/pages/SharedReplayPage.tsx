import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiGet, ApiError } from "../../lib/api";
import { AgentMessages } from "../replay/AgentMessages";
import { CategoryFilters } from "../replay/CategoryFilters";
import { EventStream } from "../replay/EventStream";
import { Inspector } from "../replay/Inspector";
import { MarkerList } from "../replay/MarkerList";
import { PlaybackControls } from "../replay/PlaybackControls";
import { ReplayVaStage } from "../replay/ReplayVaStage";
import { Timeline } from "../replay/Timeline";
import type { ReplayMarker, ReplayPayload } from "../replay/types";
import { useReplayEngine } from "../replay/useReplayEngine";
import "../../styles/replay.css";

interface SharedReplayResponse {
  session: { id: string; status: string; created_at: string | null; mode: string };
  study: { name: string; slug: string };
  markers: ReplayMarker[];
  payload: ReplayPayload;
}

export function SharedReplayPage() {
  const { token = "" } = useParams();
  const [data, setData] = useState<SharedReplayResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<SharedReplayResponse>(`/api/shared/replay/${encodeURIComponent(token)}`)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Something went wrong."));
  }, [token]);

  return (
    <div className="admin-main" style={{ maxWidth: 1280, margin: "0 auto", padding: "20px 24px" }}>
      <div className="page-head">
        <div>
          <div className="breadcrumb">Shared replay · read-only</div>
          <h1>{data ? data.study.name : "Replay"}</h1>
          {data && (
            <p className="muted">
              Session <code>{data.session.id}</code>
              {data.session.created_at && <> · {new Date(data.session.created_at).toLocaleString()}</>} ·{" "}
              {data.payload.n_events} events
            </p>
          )}
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && data.payload.timeline.length === 0 && (
        <div className="empty">
          <p>This session has no events recorded.</p>
        </div>
      )}
      {data && data.payload.timeline.length > 0 && <SharedReplayBody data={data} />}
    </div>
  );
}

function SharedReplayBody({ data }: { data: SharedReplayResponse }) {
  const engine = useReplayEngine(data.payload);
  const currentIndex = engine.indexAt(engine.currentT);
  const stateAtPlayhead = engine.snapshotAt(currentIndex).state;
  const activeTaskLabel = engine.taskAt(currentIndex);

  const changeAtCurrent = (() => {
    for (let i = currentIndex; i >= 0; i--) {
      const d = engine.deltas[i];
      if (d && Object.keys(d.delta).length) return d;
    }
    return null;
  })();
  const changedKeys = new Set(changeAtCurrent ? Object.keys(changeAtCurrent.delta) : []);

  return (
    <div className="replay-shell">
      <div className="replay-main-grid">
        <div className="replay-main-left">
          {engine.videoMode ? (
            <ReplayVaStage payload={data.payload} engine={engine} vaStatus="ready" vaIframeUrl={null} />
          ) : (
            <section className="replay-va card">
              <header className="replay-section-head">
                <h2>Participant POV</h2>
                <span className="muted small">no screen recording in this session</span>
              </header>
              <div className="replay-va-stage" style={{ display: "grid", placeItems: "center" }}>
                <p className="muted" style={{ maxWidth: 420, textAlign: "center" }}>
                  This session has no screen recording. Follow the session through the timeline and the
                  WorldState inspector below.
                </p>
              </div>
            </section>
          )}

          <div className="replay-timeline-card">
            <CategoryFilters
              filters={engine.filters}
              visible={engine.visible}
              classified={engine.classified}
              onToggle={engine.toggleFilter}
            />
            <Timeline
              engine={engine}
              markers={data.markers}
              onScrub={(t) => engine.setT(t)}
              onMarkerClick={(t) => engine.setT(t)}
            />
            <PlaybackControls
              playing={engine.playing}
              currentT={engine.currentT}
              tMax={engine.tMax}
              speed={engine.speed}
              status={engine.videoMode ? "ready" : "read-only"}
              onJumpStart={engine.jumpStart}
              onStepBack={engine.stepBack}
              onPlayPause={() => (engine.playing ? engine.pause() : engine.play())}
              onStepForward={engine.stepForward}
              onSpeedChange={engine.setSpeed}
            />
          </div>
        </div>
      </div>

      <div className="replay-lower">
        <EventStream
          classified={engine.classified}
          visible={engine.visible}
          currentIndex={currentIndex}
          activeTaskLabel={activeTaskLabel}
          onSelect={(t) => engine.setT(t)}
        />
        <Inspector
          currentT={engine.currentT}
          changeAtCurrent={changeAtCurrent}
          state={stateAtPlayhead}
          changedKeys={changedKeys}
          onKeyClick={() => {}}
        />
        <MarkerList markers={data.markers} onJump={(t) => engine.setT(t)} />
      </div>

      <AgentMessages classified={engine.classified} currentT={engine.currentT} onJump={(t) => engine.setT(t)} />
    </div>
  );
}
