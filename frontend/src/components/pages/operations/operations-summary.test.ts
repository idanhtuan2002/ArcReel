import { describe, expect, it } from "vitest";

import { summarizeOperations } from "./operations-summary";

const project = (name: string, phase?: string) => ({ name, title: name.toUpperCase(), status: phase ? { phase } : {} }) as never;
const run = (run_id: string, phase: string) => ({ run_id, phase, idea: `idea ${run_id}` }) as never;
const task = (project_name: string, status: string) => ({ project_name, status }) as never;

describe("summarizeOperations", () => {
  it("collects decisions, running work and each project's stage across projects", () => {
    const summary = summarizeOperations(
      [project("a", "script"), project("b", "preparation"), project("c")],
      { a: [run("r1", "READY_FOR_APPROVAL"), run("r2", "COMMITTED")], b: [run("r3", "RUNNING")] },
      [task("a", "running"), task("a", "queued"), task("c", "running")],
    );
    expect(summary.decisions.map((item) => [item.project, item.runId])).toEqual([["a", "r1"]]);
    expect(summary.running.map((item) => [item.project, item.storyRuns, item.tasks])).toEqual([
      ["a", 0, 2],
      ["b", 1, 0],
      ["c", 0, 1],
    ]);
    expect(summary.stages.map((item) => [item.project, item.stage])).toEqual([
      ["a", "adapt"],
      ["b", "create"],
      ["c", null],
    ]);
  });

  it("is empty when nothing waits or runs", () => {
    const summary = summarizeOperations([project("a", "completed")], {}, []);
    expect(summary.decisions).toEqual([]);
    expect(summary.running).toEqual([]);
    expect(summary.stages[0].stage).toBe("package");
  });
});
