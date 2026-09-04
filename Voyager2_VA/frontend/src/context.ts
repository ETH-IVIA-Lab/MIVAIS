import { createMivaisContext } from "mivais-va-client/react";
import type { VoyagerAction, VoyagerWorldState } from "./types";

export const { MivaisProvider: VoyagerProvider, useMivais: useVoyager } = createMivaisContext<
  VoyagerWorldState,
  VoyagerAction
>();
