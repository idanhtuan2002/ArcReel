import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "../api/productionRunClient";
import { API } from "@/api";
import { useProjectsStore } from "@/stores/projects-store";
import type { RunList, RunSnapshot } from "../api/types";
import { ProjectOutcome } from "./ProjectOutcome";

function run(over: Partial<RunSnapshot>): RunSnapshot {
  return {
    run_id: "r",
    status: "SUCCEEDED",
    stage: "EXPORT",
    targets: ["episode:1"],
    completed_targets: [],
    reason: null,
    ...over,
  } as RunSnapshot;
}

describe("ProjectOutcome", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the finished film of the older run and says in words why the latest run stopped", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({
      start: {},
      runs: [
        run({ run_id: "new", status: "BLOCKED_CONFIGURATION", stage: "ADAPTATION", targets: ["episode:2"], reason: "ADAPTATION_FAILED" }),
        run({
          run_id: "old",
          completed_targets: [
            { target: "episode:1", archive_digest: "a", archive_size: 1, final_digest: "f", quality_decision: "REWORK" },
          ],
        }),
      ],
    } as unknown as RunList);
    const onOpen = vi.fn();

    render(<ProjectOutcome projectName="demo" titles={{ 1: "Chuyến đò cuối" }} onOpenDetails={onOpen} />);

    expect(await screen.findByRole("button", { name: "观看第 1 集" })).toBeInTheDocument();
    expect(screen.getByText("Chuyến đò cuối")).toBeInTheDocument();
    expect(screen.getByText("未通过审片 · 最佳版本")).toBeInTheDocument();
    expect(screen.getByText("第 2 集停在「改编」")).toBeInTheDocument();
    expect(screen.getByText("写作模型多次尝试后仍未能把本集改编成剧本")).toBeInTheDocument();
    expect(screen.queryByText("ADAPTATION_FAILED")).not.toBeInTheDocument();
  });

  it("offers to resume, and to reset the plan from the stopped episode after naming the episodes it would clear", async () => {
    const stoppedRun = run({
      run_id: "new",
      status: "BLOCKED_CONFIGURATION",
      stage: "ADAPTATION",
      targets: ["episode:2"],
      reason: "ADAPTATION_FAILED",
      version: 4,
      input_digest: "sha256:i",
      policy_digest: "sha256:p",
    } as Partial<RunSnapshot>);
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: {}, runs: [stoppedRun] } as unknown as RunList);
    const control = vi.spyOn(client, "controlProductionRun").mockResolvedValue({ ...stoppedRun, status: "RUNNING" });
    const request = vi
      .spyOn(API, "request")
      .mockResolvedValueOnce({ confirmation_required: true, consumed_episodes: [2] })
      .mockResolvedValueOnce({ confirmation_required: false, consumed_episodes: [] });
    const refreshProject = vi.fn().mockResolvedValue({ status: "ok" });
    useProjectsStore.setState({ refreshProject } as never);
    const user = userEvent.setup();

    render(<ProjectOutcome projectName="demo" titles={{}} onOpenDetails={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "从第 2 集重置分集规划" }));
    expect(await screen.findByText(/第 2 集已有剧本或媒体/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "仍然重置" }));
    expect(request.mock.calls.map(([, init]) => JSON.parse(String(init?.body)))).toEqual([
      { from_episode: 2, confirm_consumed: false },
      { from_episode: 2, confirm_consumed: true },
    ]);
    expect(refreshProject).toHaveBeenCalledWith("demo");
    expect(screen.getByRole("button", { name: "打开模型设置" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "继续" }));
    expect(control).toHaveBeenCalledWith(
      "demo",
      "new",
      "resume",
      expect.objectContaining({ expected_version: 4, expected_input_digest: "sha256:i", policy_digest: "sha256:p" }),
    );
  });
});
