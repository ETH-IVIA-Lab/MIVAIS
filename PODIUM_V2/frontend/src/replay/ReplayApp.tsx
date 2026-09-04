import { ConnectedUsersBar } from "../components/ConnectedUsersBar";
import { CursorOverlay } from "../components/CursorOverlay";
import { NudgePanel } from "../components/NudgePanel";
import { RankingTable } from "../components/RankingTable";
import { WeightBars } from "../components/WeightBars";
import { PlaybackControls } from "./PlaybackControls";
import { RecordingSelect } from "./RecordingSelect";
import { Timeline } from "./Timeline";
import { usePlayback } from "./usePlayback";

function fmtTime(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function ReplayApp() {
  const p = usePlayback();
  const numericCols = p.worldState.numeric_cols ?? [];

  const statusText = p.loading
    ? "Loading recording…"
    : p.events.length
      ? `${p.events.length} events · ${fmtTime(p.totalT)}`
      : "No recording loaded";

  return (
    <>
      <header>
        <h1>PODIUM</h1>
        <div className="replay-badge">⏺ Replay</div>
        <RecordingSelect recordings={p.recordings} selected={p.selected} onSelect={p.loadRecording} statusText={statusText} />
        <ConnectedUsersBar users={p.connectedUsers} ownSessionId="" />
      </header>

      <main>
        <div className="col" id="rank-section">
          <div className="pnl-hdr">
            <div className="pnl-hdr-left">
              Ranking <span className="tag tag-svm">svm_ranker</span>
            </div>
          </div>
          <div className="scrollable">
            <RankingTable
              numericCols={numericCols}
              rankedItems={p.worldState.ranked_items ?? []}
              displayOrder={p.worldState.display_order ?? []}
              dataset={p.worldState.dataset ?? []}
              draggable={false}
              cursors={p.cursors}
            />
          </div>
        </div>

        <div className="col" id="weight-col">
          <div className="pnl-hdr">
            Weights <span className="tag tag-svm">svm_ranker</span>
          </div>
          <WeightBars numericCols={numericCols} weights={p.worldState.weights ?? {}} />
          <div className="divider" />
          <div className="pnl-hdr">
            Nudges <span className="tag tag-usr">user</span>
          </div>
          <NudgePanel numericCols={numericCols} nudges={p.worldState.session_nudges ?? {}} interactive={false} />
        </div>

      </main>

      <div id="replay-bar">
        <Timeline events={p.events} totalT={p.totalT} currentT={p.currentT} onSeekPct={(pct) => p.seekTo(pct * p.totalT)} />
        <PlaybackControls
          playing={p.playing}
          currentT={p.currentT}
          totalT={p.totalT}
          speed={p.speed}
          eventCount={p.events.length}
          disabled={!p.events.length}
          onTogglePlay={p.togglePlay}
          onRestart={() => p.seekTo(0)}
          onSpeedChange={p.changeSpeed}
        />
      </div>

      <CursorOverlay cursors={p.cursors} ownSessionId="" />

      {p.loading && (
        <div id="loading">
          <div className="spin" />
          <span id="loading-text">Loading recording…</span>
        </div>
      )}
    </>
  );
}
