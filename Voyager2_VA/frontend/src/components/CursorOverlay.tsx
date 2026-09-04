
import { CursorOverlay as BaseCursorOverlay } from "mivais-va-client/react";
import type { CursorMap } from "mivais-va-client";
import { VOYAGER_USER_PALETTE } from "./ConnectedUsersBar";

export function CursorOverlay({ cursors, ownSessionId }: { cursors: CursorMap; ownSessionId: string }) {
  return (
    <BaseCursorOverlay
      cursors={cursors}
      ownSessionId={ownSessionId}
      palette={VOYAGER_USER_PALETTE}
      id="cursorOverlay"
    />
  );
}
