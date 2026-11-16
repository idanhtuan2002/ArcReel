import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "../api/productionRunClient";
import type { RunList, RunSnapshot } from "../api/types";
import { ActiveRunNotice } from "./ActiveRunNotice";

const RUN = {
  run_id: "r1",
  status: "WAITING_TASK",
  stage: "MEDIA",
  targets: ["episode:2"],
  completed_targets: [],
  reason: null,
  version: 7,
  input_digest: "sha256:i",
  policy_digest: "sha256:p",
} as unknown as RunSnapshot;

describe("ActiveRunNotice", () => {
  afterEach(() => vi.restoreAllMocks());

  it("warns while a run makes media and pauses it on request", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: {}, runs: [RUN] } as unknown as RunList);
    const control = vi
      .spyOn(client, "controlProductionRun")
      .mockResolvedValue({ ...RUN, status: "PAUSED" } as RunSnapshot);

    render(<ActiveRunNotice projectName="demo" />);
    await userEvent.click(await screen.findByRole("button", { name: "暂停运行" }));
    // The banner's button only asks; nothing is paused until the question is answered.
    expect(control).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "不暂停" }));
    expect(screen.queryByRole("button", { name: "暂停" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "暂停运行" }));
    await userEvent.click(screen.getByRole("button", { name: "暂停" }));

    expect(control).toHaveBeenCalledWith(
      "demo",
      "r1",
      "pause",
      expect.objectContaining({ expected_version: 7, expected_input_digest: "sha256:i", policy_digest: "sha256:p" }),
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("says nothing when the run has stopped", async () => {
    const list = vi
      .spyOn(client, "listProductionRuns")
      .mockResolvedValue({ start: {}, runs: [{ ...RUN, status: "BLOCKED_CONFIGURATION" }] } as unknown as RunList);
    render(<ActiveRunNotice projectName="demo" />);
    await vi.waitFor(() => expect(list).toHaveBeenCalled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
