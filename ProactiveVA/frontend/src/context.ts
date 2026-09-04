import { createMivaisContext } from "mivais-va-client/react";
import type { ProactiveAction, ProactiveWorldState } from "./types";

export const { MivaisProvider: ProactiveProvider, useMivais: useProactive } = createMivaisContext<
  ProactiveWorldState,
  ProactiveAction
>();
