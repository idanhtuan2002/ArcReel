import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "../api/productionRunClient";
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
});
