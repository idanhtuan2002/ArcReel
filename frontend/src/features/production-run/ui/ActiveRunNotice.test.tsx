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

  it("warns while a run makes media and links to the run's controls instead of holding one", async () => {
    window.history.pushState({}, "", "/app/projects/demo/characters");
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: {}, runs: [RUN] } as unknown as RunList);
    const control = vi.spyOn(client, "controlProductionRun");

    render(<ActiveRunNotice projectName="demo" />);
    expect(await screen.findByRole("status")).toHaveTextContent("第 2 集");
    expect(screen.queryByRole("button", { name: "暂停运行" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "查看并控制本次运行" }));
    expect(window.location.pathname).toBe("/app/projects/demo");
    expect(control).not.toHaveBeenCalled();
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
