// The shared multi-user cursor overlay (and the row-anchored cursor-state
// helper) live in the client library; the app only owns the .cursor-ptr /
// .cursor-label styling.
export { CursorOverlay, deriveRowCursorState } from "mivais-va-client/react";
