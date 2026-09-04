import { usePodium } from "../context";
import { NudgePanel } from "../components/NudgePanel";
import { ScanLine } from "../components/ScanLine";
import { WeightBars } from "../components/WeightBars";
import { useAgentActivity } from "./useAgentActivity";

export function WeightColumn() {
  const { worldState, sendAction, canWrite } = usePodium();
  const svm = useAgentActivity("svm_ranker");
  const numericCols = worldState.numeric_cols ?? [];
  const weights = worldState.weights ?? {};
  const nudges = worldState.session_nudges ?? {};
  const canNudge = canWrite("session_nudges");

  return (
    <div className={`col${svm.glowOn ? " svm-active" : ""}`} id="weight-col" key={svm.glowNonce}>
      <ScanLine variant="svm" run={svm.scanOn} nonce={svm.scanNonce} />
      <div className="pnl-hdr">
        <div className="pnl-hdr-left">
          Weights
          <div className={`thinking${svm.thinkOn ? " visible" : ""}`}>
            <span />
            <span />
            <span />
          </div>
        </div>
        <span className="tag tag-svm">svm_ranker</span>
      </div>
      <WeightBars numericCols={numericCols} weights={weights} />
      <div className="divider" />
      <div className="pnl-hdr">
        Nudges <span className="tag tag-usr">user</span>
      </div>
      <div className={canNudge ? undefined : "perm-disabled"}>
        <NudgePanel
          numericCols={numericCols}
          nudges={nudges}
          interactive={canNudge}
          onNudge={(col, dir) => {
            const next = { ...nudges };
            if (dir === 0) delete next[col];
            else next[col] = dir;
            sendAction({ action: "set_nudges", nudges: next });
          }}
        />
      </div>
    </div>
  );
}
