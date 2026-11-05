"use client";

import { createContext, useContext } from "react";
import type { Settings } from "@/lib/api";

export type ChatActions = {
  settings: Settings | null;
  streaming: boolean;
  /** Bumped after every run so plan cards re-fetch their status. */
  version: number;
  runPlan: (planId: string, dryRun: boolean) => void;
  cancelRun: (runId: string) => void;
};

export const ActionsContext = createContext<ChatActions | null>(null);

export function useActions(): ChatActions {
  const ctx = useContext(ActionsContext);
  if (!ctx) throw new Error("ActionsContext missing");
  return ctx;
}
