import { useEffect } from "react";
import { create } from "zustand";
import { listProductionRuns } from "./api/productionRunClient";
import type { RunSnapshot } from "./api/types";

/** How often a project's runs are read while something on the page shows them. */
export const RUNS_REFRESH_MS = 15000;

interface RunsState {
  /** Each project's runs, newest first, as last read; absent until the first read. */
  byProject: Record<string, RunSnapshot[]>;
  setRuns: (project: string, runs: RunSnapshot[]) => void;
  /** Puts a run a command just returned in place of its older snapshot (a pause or a resume shows at once). */
  putRun: (project: string, run: RunSnapshot) => void;
}

export const useRunsStore = create<RunsState>((set) => ({
  byProject: {},
  setRuns: (project, runs) => set((state) => ({ byProject: { ...state.byProject, [project]: runs } })),
  putRun: (project, run) =>
    set((state) => {
      const runs = state.byProject[project] ?? [];
      const rest = runs.filter((item) => item.run_id !== run.run_id);
      return { byProject: { ...state.byProject, [project]: [run, ...rest] } };
    }),
}));

interface Poller {
  users: number;
  timer: number;
  controller: AbortController;
}

const pollers = new Map<string, Poller>();

function read(project: string, poller: Poller): void {
  poller.controller.abort();
  poller.controller = new AbortController();
  const { signal } = poller.controller;
  listProductionRuns(project, { signal })
    .then((list) => {
      if (!signal.aborted) useRunsStore.getState().setRuns(project, list.runs);
    })
    .catch(() => {
      // A summary, not a source of truth: the operations details report their own errors.
    });
}

/**
 * The project's runs, newest first (``null`` until read). Every component on the page shares one reading loop per
 * project, which runs while at least one of them is mounted.
 */
export function useProjectRuns(project: string | null): RunSnapshot[] | null {
  const runs = useRunsStore((state) => (project ? state.byProject[project] : undefined));
  useEffect(() => {
    if (!project) return;
    const poller = pollers.get(project);
    if (poller) {
      poller.users += 1;
    } else {
      const started: Poller = { users: 1, timer: 0, controller: new AbortController() };
      started.timer = window.setInterval(() => read(project, started), RUNS_REFRESH_MS);
      pollers.set(project, started);
      read(project, started);
    }
    return () => {
      const current = pollers.get(project);
      if (!current) return;
      current.users -= 1;
      if (current.users === 0) {
        window.clearInterval(current.timer);
        current.controller.abort();
        pollers.delete(project);
      }
    };
  }, [project]);
  return runs ?? null;
}
