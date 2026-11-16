import type { EpisodesSummary } from "@/types/project";

/**
 * Which episode a project's workflow phase is about, so "Script" next to a project with episode 1 finished reads
 * "Script · episode 2" instead of contradicting the finished film. Episodes are made in order, so the phase is about
 * the first unfinished one. ``null`` when no episode is finished yet (the phase is about the whole project) and
 * ``"done"`` once every planned episode is finished.
 */
export function phaseEpisode(summary: EpisodesSummary | null | undefined): number | "done" | null {
  if (!summary || summary.total <= 0 || summary.completed <= 0) return null;
  if (summary.completed >= summary.total) return "done";
  return summary.completed + 1;
}
