import { usePodium } from "../context";
import { RankingTable, buildItems } from "../components/RankingTable";
import { ScanLine } from "../components/ScanLine";
import { getRowName } from "../types";
import { useAgentActivity } from "./useAgentActivity";

export function RankingPanel({
  highlightRowName,
  highlightNonce,
}: {
  highlightRowName?: string | null;
  highlightNonce?: number;
}) {
  const { worldState, sessionId, cursors, sendAction, sendCursor, canWrite, canPublish } = usePodium();
  const svm = useAgentActivity("svm_ranker");

  const numericCols = worldState.numeric_cols ?? [];
  const rankedItems = worldState.ranked_items ?? [];
  const displayOrder = worldState.display_order ?? [];
  const dataset = worldState.dataset ?? [];
  const canDrag = canWrite("display_order");
  const canTrigger = canPublish("rank_all.request");

  const computeWeights = () => {
    const items = buildItems(rankedItems, displayOrder);
    const ranking = items.map((item) => {
      const name = getRowName(item);
      const idx = dataset.findIndex((d) => getRowName(d) === name);
      return idx >= 0 ? idx : 0;
    });
    sendAction({ action: "compute_weights", ranking });
  };

  return (
    <div className={`col${svm.glowOn ? " svm-active" : ""}`} id="rank-section" key={svm.glowNonce}>
      <ScanLine variant="svm" run={svm.scanOn} nonce={svm.scanNonce} />
      <div className="pnl-hdr">
        <div className="pnl-hdr-left">
          Ranking — drag to express preferences
          <div className={`thinking${svm.thinkOn ? " visible" : ""}`}>
            <span />
            <span />
            <span />
          </div>
        </div>
        <span className="tag tag-svm">svm_ranker</span>
      </div>
      <div className={`action-bar${canTrigger ? "" : " perm-disabled"}`}>
        <button type="button" className="btn primary" onClick={computeWeights}>
          Compute Weights
        </button>
        <button type="button" className="btn" onClick={() => sendAction({ action: "rank_all" })}>
          Rank All
        </button>
      </div>
      <div className="svm-status-bar">
        {worldState.svm_status?.message ?? "Drag your favorites into the top 10, then click Compute Weights"}
      </div>
      <div className="scrollable">
        <RankingTable
          numericCols={numericCols}
          rankedItems={rankedItems}
          displayOrder={displayOrder}
          dataset={dataset}
          draggable={canDrag}
          cursors={cursors}
          ownSessionId={sessionId}
          highlightRowName={highlightRowName}
          highlightNonce={highlightNonce}
          onRowHover={(name) => sendCursor(name)}
          onDragStateChange={(dragging, dragOver) => sendAction({ action: "drag_update", dragging, drag_over: dragOver })}
          onReorder={(order) => sendAction({ action: "drop_order", display_order: order })}
        />
      </div>
    </div>
  );
}
