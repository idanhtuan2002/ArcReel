import { afterEach, describe, expect, it, vi } from "vitest";

import { API } from "@/api";
import { resumeProductionRun } from "./productionRunClient";

const run = {
  run_id: "r1",
  version: 4,
  input_digest: "sha256:old",
  policy_digest: "sha256:p",
} as const;

afterEach(() => vi.restoreAllMocks());

function body(call: unknown[]): unknown {
  return JSON.parse(String((call[1] as RequestInit).body));
}

describe("resumeProductionRun", () => {
  it("resumes a run blocked by changed inputs on the project's inputs as they are now", async () => {
    const request = vi
      .spyOn(API, "request")
      .mockResolvedValueOnce({ start: { enabled: true, input_digest: "sha256:now" }, runs: [] })
      .mockResolvedValueOnce({ run_id: "r1", status: "RUNNING" });

    await resumeProductionRun("demo", { ...run, status: "BLOCKED_INPUT_CHANGED" }, "cmd-1");

    expect(request).toHaveBeenCalledTimes(2);
    expect(request.mock.calls[1][0]).toBe("/projects/demo/production-runs/r1/resume");
    expect(body(request.mock.calls[1])).toEqual({
      command_id: "cmd-1",
      expected_version: 4,
      expected_input_digest: "sha256:now",
      policy_digest: "sha256:p",
    });
  });

  it("resumes any other stopped run on the inputs it was bound to", async () => {
    const request = vi.spyOn(API, "request").mockResolvedValueOnce({ run_id: "r1", status: "RUNNING" });

    await resumeProductionRun("demo", { ...run, status: "BLOCKED_CONFIGURATION" }, "cmd-2");

    expect(request).toHaveBeenCalledTimes(1);
    expect(body(request.mock.calls[0])).toMatchObject({ expected_input_digest: "sha256:old" });
  });

  it("keeps the bound inputs when the project offers no digest to resume on", async () => {
    const request = vi
      .spyOn(API, "request")
      .mockResolvedValueOnce({ start: { enabled: false, reason: "RELEASE_GATE_PENDING" }, runs: [] })
      .mockResolvedValueOnce({ run_id: "r1", status: "RUNNING" });

    await resumeProductionRun("demo", { ...run, status: "BLOCKED_INPUT_CHANGED" }, "cmd-3");

    expect(body(request.mock.calls[1])).toMatchObject({ expected_input_digest: "sha256:old" });
  });
});
