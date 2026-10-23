import { describe, expect, it } from "vitest";

import { pendingDecisions, stageStates } from "./pipeline-stages";

const step = (id: string, state: string) => ({ id, state }) as never;
const plan = (steps: unknown[], extra: Record<string, unknown> = {}) =>
  ({ steps, status: { source_revision: "rev-1", state: "SCRIPT_PLAN", ...extra }, blockers: [] }) as never;

describe("stageStates", () => {
  it("aggregates server workflow steps onto North Star stages", () => {
    const states = stageStates(
      plan([
        step("episode_plan", "completed"),
        step("script_plan_content", "active"),
        step("asset_inventory", "blocked"),
        step("storyboard", "pending"),
        step("video", "ready"),
      ]),
      [],
    );
    expect(states.discover).toBe("soon");
    expect(states.research).toBe("soon");
    expect(states.create).toBe("done");
    expect(states.adapt).toBe("active");
    expect(states.prepare).toBe("attention");
    expect(states.direct).toBe("todo");
    expect(states.produce).toBe("ready");
  });

  it("puts the story run state on the create stage before a source exists", () => {
    expect(stageStates(plan([], { source_revision: null }), [{ phase: "RUNNING" } as never]).create).toBe("active");
    expect(stageStates(plan([], { source_revision: null }), [{ phase: "READY_FOR_APPROVAL" } as never]).create).toBe("attention");
    expect(stageStates(plan([], { source_revision: null }), []).create).toBe("ready");
    expect(stageStates(null, []).create).toBe("ready");
  });

  it("marks package ready only when the server says export is ready", () => {
    expect(stageStates(plan([], { state: "EXPORT_READY" }), []).package).toBe("ready");
    expect(stageStates(plan([]), []).package).toBe("todo");
  });
});

describe("pendingDecisions", () => {
  it("lists story runs that wait for the Human", () => {
    const runs = [
      { run_id: "a", phase: "READY_FOR_APPROVAL", idea: "Đò cuối" },
      { run_id: "b", phase: "RUNNING", idea: "x" },
      { run_id: "c", phase: "COMMITTED", idea: "y" },
      { run_id: "d", phase: "BLOCKED_QUALITY", idea: "z" },
    ] as never[];
    expect(pendingDecisions(runs).map((run) => run.run_id)).toEqual(["a", "d"]);
  });
});
