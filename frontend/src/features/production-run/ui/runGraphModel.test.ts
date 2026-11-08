import { describe, expect, it } from "vitest";

import type { RunSnapshot } from "../api/types";
import { STAGES_PER_ROW, runGraph } from "./runGraphModel";

function run(changes: Partial<RunSnapshot> = {}): RunSnapshot {
  return {
    user_id: "u",
    project_name: "alpha",
    run_id: "run-1",
    status: "RUNNING",
    stage: "MEDIA",
    generation: 2,
    version: 3,
    input_digest: "sha256:in",
    policy_digest: "sha256:auto",
    mode_policy_digests: { auto: "sha256:auto", semi: "sha256:semi" },
    policy: { mode: "auto" },
    targets: ["episode:1"],
    completed_targets: [],
    pending_review: null,
    reason: null,
    created_at: "2026-11-01T00:00:00Z",
    ...changes,
  } as RunSnapshot;
}

describe("runGraph", () => {
  it("lays the stages out as one line over two rows and marks the current stage", () => {
    const { nodes, edges } = runGraph(run(), { BRIEF: { ms: 45_000, running: false } });

    const stages = nodes.filter((node) => node.data.kind === "stage");
    expect(stages).toHaveLength(15);
    expect(stages[0].data).toMatchObject({ stage: "BRIEF", state: "done", duration: "45s" });
    expect(stages.find((node) => node.id === "MEDIA")?.data.state).toBe("current");
    expect(stages.find((node) => node.id === "EXPORT")?.data.state).toBe("pending");
    // The second row runs back from right to left, so its first stage sits under the first row's last one.
    expect(stages[STAGES_PER_ROW].position).toEqual({ x: stages[STAGES_PER_ROW - 1].position.x, y: 110 });
    expect(edges.filter((edge) => !edge.id.startsWith("repair:") && !edge.id.startsWith("EXPORT->"))).toHaveLength(14);
  });

  it("draws each repair as a loop back from QUALITY and the episodes after EXPORT", () => {
    const { nodes, edges } = runGraph(
      run({
        status: "SUCCEEDED",
        stage: "EXPORT",
        repair_counts: [{ stage: "MEDIA", unit_key: "episode:1", count: 2 }],
        completed_targets: [{ target: "episode:1" } as RunSnapshot["completed_targets"][number]],
      }),
      {},
    );

    expect(edges.find((edge) => edge.id === "repair:MEDIA:episode:1")).toMatchObject({
      source: "QUALITY",
      target: "MEDIA",
      label: "×2",
    });
    expect(nodes.every((node) => node.data.kind !== "stage" || node.data.state === "done")).toBe(true);
    expect(nodes.find((node) => node.id === "target:episode:1")?.data).toMatchObject({ done: true });
  });
});
