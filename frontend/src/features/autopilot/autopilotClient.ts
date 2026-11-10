/** ADR-0124: a project's autopilot — whether it is on, with what, and what it does next. */

import { API } from "@/api";

export interface StoryAutopilot {
  idea: string;
  book_chapters: number;
  direction?: string;
}

export interface FilmAutopilot {
  episodes_per_run: number;
}

export interface AutopilotDelegation {
  version: number;
  state: "ENABLED" | "DISABLED";
  kind: "story" | "film";
  mode: "auto" | "semi";
  story: StoryAutopilot | null;
  film: FilmAutopilot | null;
  created_at: string;
}

export type AutopilotStateName = "off" | "waiting" | "halted" | "finished" | "ready";

export interface AutopilotView {
  available: boolean;
  delegation: AutopilotDelegation | null;
  status: { state: AutopilotStateName; run_id: string | null; reason: string | null };
}

export interface AutopilotChange {
  enabled: boolean;
  mode?: "auto" | "semi";
  story?: StoryAutopilot;
  film?: FilmAutopilot;
}

const path = (projectName: string) => `/projects/${encodeURIComponent(projectName)}/autopilot`;

export function getAutopilot(projectName: string, signal?: AbortSignal): Promise<AutopilotView> {
  return API.request<AutopilotView>(path(projectName), { signal });
}

export function setAutopilot(projectName: string, change: AutopilotChange): Promise<AutopilotView> {
  return API.request<AutopilotView>(path(projectName), {
    method: "PUT",
    body: JSON.stringify({ command_id: `autopilot-${crypto.randomUUID()}`, ...change }),
  });
}
