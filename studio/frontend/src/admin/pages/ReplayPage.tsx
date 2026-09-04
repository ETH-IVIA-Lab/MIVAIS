import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiDelete, apiGet, apiPost, ApiError } from "../../lib/api";
import type { Study } from "../../lib/types";
import { CategoryFilters } from "../replay/CategoryFilters";
import { AgentMessages } from "../replay/AgentMessages";
import { EventStream } from "../replay/EventStream";
import { HeartRateStrip } from "../replay/HeartRateStrip";
import { Inspector } from "../replay/Inspector";
import { KeyHistoryDialog } from "../replay/KeyHistoryDialog";
import type { KeyChange } from "../replay/KeyHistoryDialog";
import { MarkerDialog } from "../replay/MarkerDialog";
import { MarkerList } from "../replay/MarkerList";
import { NotesPanel } from "../replay/NotesPanel";
import { PlaybackControls } from "../replay/PlaybackControls";
import { ReplayVaStage } from "../replay/ReplayVaStage";
import { SensorChannelStrip } from "../replay/SensorChannelStrip";
import { Timeline } from "../replay/Timeline";
import { TranscriptPanel } from "../replay/TranscriptPanel";
import type { AdminSession } from "../types";
import type { ReplayMarker, ReplayPayload } from "../replay/types";
import { useReplayEngine } from "../replay/useReplayEngine";
import { useReplayVA } from "../replay/useReplayVA";
import "../../styles/replay.css";

interface ReplayResponse {
  session: AdminSession;
  study: Study;
  payload: ReplayPayload;
}

export function ReplayPage() {
  const { id = "" } = useParams();
  const [data, setData] = useState<ReplayResponse | null>(null);
  const [markers, setMarkers] = useState<ReplayMarker[]>([]);
  const [markerDialogOpen, setMarkerDialogOpen] = useState(false);
  const [markerAtT, setMarkerAtT] = useState(0);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [shareCopied, setShareCopied] = useState(false);

  useEffect(() => {
    apiGet<ReplayResponse>(`/api/admin/replay/${id}`).then((res) => {
      setData(res);
      setMarkers(res.session.markers as unknown as ReplayMarker[]);
      const token = (res.session as unknown as { share_token?: string | null }).share_token;
      setShareUrl(token ? `${window.location.origin}/admin/shared/${token}` : null);
    });
  }, [id]);

  async function onShare() {
    const res = await apiPost<{ token: string; url: string }>(`/api/admin/sessions/${id}/share`, {});
    const url = `${window.location.origin}${res.url}`;
    setShareUrl(url);
    try {
      await navigator.clipboard.writeText(url);
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 2000);
    } catch {
      // clipboard unavailable — the URL is still shown inline
    }
  }

  async function onUnshare() {
    await apiDelete(`/api/admin/sessions/${id}/share`);
    setShareUrl(null);
  }

  const canReplay = !!data && data.payload.timeline.length > 0 && (data.payload.snapshots.length > 0 || !!data.payload.video);

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="breadcrumb">
            {data && (
              <>
                <Link to="/">Studies</Link> / <Link to={`/studies/${data.study.slug}`}>{data.study.name}</Link> /{" "}
                <Link to={`/sessions/${id}`}>Session</Link> / Replay
              </>
            )}
          </div>
          <h1>Replay</h1>
          {data && (
            <p className="muted" style={{ margin: 0 }}>
              <code>{id}</code> · {data.payload.n_events} events
            </p>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {shareUrl ? (
            <>
              <button
                type="button"
                className="btn ghost"
                title="Copy the read-only share link"
                onClick={() => {
                  navigator.clipboard?.writeText(shareUrl).then(() => {
                    setShareCopied(true);
                    setTimeout(() => setShareCopied(false), 2000);
                  });
                }}
              >
                {shareCopied ? "Link copied ✓" : "Copy share link"}
              </button>
              <button type="button" className="btn ghost" title="Revoke the share link — it stops working immediately" onClick={onUnshare}>
                Revoke
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn ghost"
              title="Create a read-only link anyone can open — no login needed"
              onClick={onShare}
            >
              Share read-only
            </button>
          )}
          <Link to={`/sessions/${id}`} className="btn ghost">
            ← Session detail
          </Link>
        </div>
      </div>
      {shareUrl && (
        <p className="muted small mono" style={{ marginTop: -8, marginBottom: 12, wordBreak: "break-all" }}>
          {shareUrl}
        </p>
      )}

      {!data && <p className="muted">Loading…</p>}
      {data && !canReplay && data.payload.timeline.length > 0 && (
        <div className="empty">
          <p>This session was recorded but has no MIVAIS state snapshots, so there is nothing to replay visually.</p>
          <p className="muted small">
            State snapshots appear when at least one participant opens the VA iframe and produces WorldState writes. The
            participant&apos;s task answers and the Studio event log are still available on the session detail page.
          </p>
          <Link to={`/sessions/${id}`} className="button">
            ← Back to session detail
          </Link>
        </div>
      )}
      {data && data.payload.timeline.length === 0 && (
        <div className="empty">
          <p>This session has no events recorded.</p>
          <Link to={`/sessions/${id}`} className="button">
            ← Back to session detail
          </Link>
        </div>
      )}
      {data && canReplay && (
        <ReplayBody
          sessionId={id}
          payload={data.payload}
          markers={markers}
          setMarkers={setMarkers}
          markerDialogOpen={markerDialogOpen}
          setMarkerDialogOpen={setMarkerDialogOpen}
          markerAtT={markerAtT}
          setMarkerAtT={setMarkerAtT}
        />
      )}
    </div>
  );
}

function ReplayBody({
  sessionId,
  payload,
  markers,
  setMarkers,
  markerDialogOpen,
  setMarkerDialogOpen,
  markerAtT,
  setMarkerAtT,
}: {
  sessionId: string;
  payload: ReplayPayload;
  markers: ReplayMarker[];
  setMarkers: (m: ReplayMarker[] | ((prev: ReplayMarker[]) => ReplayMarker[])) => void;
  markerDialogOpen: boolean;
  setMarkerDialogOpen: (v: boolean) => void;
  markerAtT: number;
  setMarkerAtT: (v: number) => void;
}) {
  const engine = useReplayEngine(payload);
  const va = useReplayVA(sessionId, !engine.videoMode);
  const [markerError, setMarkerError] = useState<string | null>(null);
  const [markerQuote, setMarkerQuote] = useState<string>("");
  const [historyKey, setHistoryKey] = useState<string | null>(null);
  const [videoEl, setVideoEl] = useState<HTMLVideoElement | null>(null);

  useEffect(() => {
    engine.pushStateRef.current = va.pushState;
  }, [engine, va.pushState]);

  const currentIndex = engine.indexAt(engine.currentT);

  const changeAtCurrent = useMemo(() => {
    for (let i = currentIndex; i >= 0; i--) {
      const d = engine.deltas[i];
      if (d && Object.keys(d.delta).length) return d;
    }
    return null;
  }, [currentIndex, engine.deltas]);

  const changedKeys = useMemo(() => new Set(changeAtCurrent ? Object.keys(changeAtCurrent.delta) : []), [changeAtCurrent]);
  const stateAtPlayhead = engine.snapshotAt(currentIndex).state;
  const activeTaskLabel = engine.taskAt(currentIndex);

  const historyChanges: KeyChange[] = useMemo(() => {
    if (!historyKey) return [];
    const out: KeyChange[] = [];
    engine.deltas.forEach((d, i) => {
      if (d && historyKey in d.delta) {
        out.push({
          t_ms: engine.classified[i]?.t_ms ?? 0,
          cause: d.cause,
          from: d.delta[historyKey].from,
          to: d.delta[historyKey].to,
        });
      }
    });
    return out;
  }, [historyKey, engine.deltas, engine.classified]);

  async function onMarkerSubmit(kind: string, label: string) {
    const res = await apiPost<{ marker: ReplayMarker }>(`/api/admin/sessions/${sessionId}/marker`, {
      t_ms: Math.round(markerAtT),
      kind,
      label,
      quote: markerQuote,
    });
    setMarkers((prev) => [...prev, res.marker]);
    setMarkerDialogOpen(false);
    setMarkerQuote("");
  }

  async function onMarkerDelete(marker_id: string) {
    setMarkerError(null);
    try {
      await apiDelete(`/api/admin/sessions/${sessionId}/marker/${marker_id}`);
      setMarkers((prev) => prev.filter((m) => m.marker_id !== marker_id));
    } catch (err) {
      setMarkerError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }


  const transcriptVideo = engine.videoMode && engine.activeVideo?.transcribe ? engine.activeVideo : null;

  return (
    <div className="replay-shell">
      <div className={`replay-main-grid${transcriptVideo ? " with-transcript" : ""}`}>
        <div className="replay-main-left">
          <ReplayVaStage
            payload={payload}
            engine={engine}
            vaStatus={va.status}
            vaIframeUrl={va.iframeUrl}
            onVideoEl={setVideoEl}
          />

          
          <div className="replay-timeline-card">
            <PlaybackControls
              playing={engine.playing}
              currentT={engine.currentT}
              tMax={engine.tMax}
              speed={engine.speed}
              status={engine.videoMode ? "ready" : va.status}
              onJumpStart={engine.jumpStart}
              onStepBack={engine.stepBack}
              onPlayPause={() => (engine.playing ? engine.pause() : engine.play())}
              onStepForward={engine.stepForward}
              onMark={() => {
                setMarkerAtT(engine.currentT);
                setMarkerQuote("");
                setMarkerDialogOpen(true);
              }}
              onSpeedChange={engine.setSpeed}
            />
            <CategoryFilters filters={engine.filters} visible={engine.visible} classified={engine.classified} onToggle={engine.toggleFilter} />
            <HeartRateStrip samples={payload.heart_rate} participants={payload.participants} tMax={engine.tMax} currentT={engine.currentT} />
            {Object.entries(payload.sensor_channels ?? {}).map(([channel, samples]) => (
              <SensorChannelStrip
                key={channel}
                channel={channel}
                samples={samples}
                participants={payload.participants}
                tMax={engine.tMax}
                currentT={engine.currentT}
              />
            ))}
            <Timeline engine={engine} markers={markers} onScrub={(t) => engine.setT(t)} onMarkerClick={(t) => engine.setT(t)} />
          </div>
        </div>

        {transcriptVideo && (
          <aside className="replay-transcript-col">
            <div className="replay-transcript-inner">
              <TranscriptPanel
                sessionId={sessionId}
                video={transcriptVideo}
                videoEl={videoEl}
                onMarkText={(t_ms, quote) => {
                  setMarkerAtT(t_ms);
                  setMarkerQuote(quote);
                  setMarkerDialogOpen(true);
                }}
                onSeek={(s) => {
                  if (videoEl) {
                    videoEl.currentTime = s;
                    videoEl.play().catch(() => {});
                  }
                }}
              />
            </div>
          </aside>
        )}
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
          onKeyClick={(k) => setHistoryKey(k)}
        />
        <div style={{height: "100%"}}>
          {markerError && <div className="alert error">{markerError}</div>}
          <MarkerList markers={markers} onJump={(t) => engine.setT(t)} onDelete={onMarkerDelete} />
        </div>
      </div>

      <AgentMessages classified={engine.classified} currentT={engine.currentT} onJump={(t) => engine.setT(t)} />

      <NotesPanel sessionId={sessionId} onJump={(t) => engine.setT(t)} />

      {historyKey && (
        <KeyHistoryDialog
          keyName={historyKey}
          changes={historyChanges}
          onClose={() => setHistoryKey(null)}
          onJump={(t) => {
            engine.setT(t);
            setHistoryKey(null);
          }}
        />
      )}

      <MarkerDialog
        open={markerDialogOpen}
        atT={markerAtT}
        quote={markerQuote}
        onClose={() => {
          setMarkerDialogOpen(false);
          setMarkerQuote("");
        }}
        onSubmit={onMarkerSubmit}
      />
    </div>
  );
}
