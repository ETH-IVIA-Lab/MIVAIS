import { useState } from "react";
import { useCursorTracking } from "mivais-va-client/react";
import { useProactive } from "./context";
import type { StaticData } from "./types";
import { TopBar } from "./components/TopBar";
import { TutorialOverlay } from "./components/TutorialOverlay";
import { ChatPanel } from "./components/ChatPanel";
import { MapView } from "./components/MapView";
import { TimelineView } from "./components/TimelineView";
import { MessagesView } from "./components/MessagesView";
import { GraphView } from "./components/GraphView";
import { NotesPanel } from "./components/NotesPanel";
import { CursorOverlay } from "./components/CursorOverlay";

export function ProactiveApp({ staticData }: { staticData: StaticData }) {
  const { sendAction, sendCursor, cursors, sessionId } = useProactive();
  const [tutorialOpen, setTutorialOpen] = useState(() => {
    try {
      return !localStorage.getItem("proactiveva.seen_tutorial");
    } catch {
      return true;
    }
  });


  useCursorTracking(sendCursor);

  const focus = (view: string) => sendAction({ action: "set_focus_view", view });

  return (
    <>
      <TopBar onShowTutorial={() => setTutorialOpen(true)} />
      {tutorialOpen && (
        <TutorialOverlay
          onClose={() => {
            setTutorialOpen(false);
            try {
              localStorage.setItem("proactiveva.seen_tutorial", "1");
            } catch {
              /* private mode */
            }
          }}
        />
      )}
      <main className="grid">
        <ChatPanel />
        <section id="va">
          <section className="panel" id="map-pane" onClickCapture={() => focus("map")}>
            <MapView staticData={staticData} />
          </section>
          <section className="panel" id="timeline-pane" onClickCapture={() => focus("timeline")}>
            <header className="subhead">Timeline — message volume</header>
            <div className="body">
              <TimelineView dataset={staticData.dataset} />
            </div>
          </section>
          <section className="panel" id="messages-pane" onClickCapture={() => focus("messages")}>
            <MessagesView dataset={staticData.dataset} />
          </section>
          <section className="panel" id="graph-pane" onClickCapture={() => focus("graph")}>
            <header className="subhead">Entity graph &amp; key entities</header>
            <div className="graph-legend">
              <span>
                <span className="swatch" style={{ background: "#ef4444" }} />
                Org
              </span>
              <span>
                <span className="swatch" style={{ background: "#f59e0b" }} />
                Tag/Topic
              </span>
              <span>
                <span className="swatch" style={{ background: "#06b6d4" }} />
                Location
              </span>
            </div>
            <div className="body">
              <GraphView dataset={staticData.dataset} />
            </div>
          </section>
        </section>
        <NotesPanel dataset={staticData.dataset} />
      </main>
      <CursorOverlay cursors={cursors} ownSessionId={sessionId} />
    </>
  );
}
