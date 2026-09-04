import { createMivaisContext } from "mivais-va-client/react";
import type { PodiumAction, PodiumWorldState } from "./types";

export const { MivaisProvider: PodiumProvider, useMivais: usePodium } = createMivaisContext<
  PodiumWorldState,
  PodiumAction
>();
