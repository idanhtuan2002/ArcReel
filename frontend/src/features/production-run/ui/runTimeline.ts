import { STAGES, type RunProgress, type RunStage } from "../api/types";

export interface StageTime {
  /** Milliseconds the stage took; for the current stage, the time since the previous stage passed. */
  ms: number;
  running: boolean;
}

/**
 * Each stage's duration from the run's timeline: a passed stage runs from the previous passed stage (or the run's
 * start) to its own pass time; the current stage, while the run is active, runs from the last pass time to `now`.
 */
export function stageTimes(
  progress: RunProgress | null,
  current: RunStage,
  active: boolean,
  now: number,
): Partial<Record<RunStage, StageTime>> {
  if (!progress?.started_at) return {};
  const finished = new Map((progress.stages ?? []).map((item) => [item.stage, Date.parse(item.finished_at)]));
  const times: Partial<Record<RunStage, StageTime>> = {};
  let previous = Date.parse(progress.started_at);
  for (const stage of STAGES) {
    const at = finished.get(stage);
    if (at !== undefined) {
      times[stage] = { ms: Math.max(0, at - previous), running: false };
      previous = Math.max(previous, at);
    }
  }
  if (active && times[current] === undefined) times[current] = { ms: Math.max(0, now - previous), running: true };
  return times;
}

/** The run's total time: to `now` while active, otherwise to the last stage pass. */
export function totalTime(progress: RunProgress | null, active: boolean, now: number): number | null {
  if (!progress?.started_at) return null;
  const started = Date.parse(progress.started_at);
  const passes = (progress.stages ?? []).map((item) => Date.parse(item.finished_at));
  const end = active ? now : passes.length ? Math.max(...passes) : null;
  return end === null ? null : Math.max(0, end - started);
}

/** A short duration such as "4h 10m", "12m" or "45s". */
export function formatDuration(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m`;
  return `${seconds}s`;
}
