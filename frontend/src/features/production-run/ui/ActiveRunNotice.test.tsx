import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "../api/productionRunClient";
import type { RunList, RunSnapshot } from "../api/types";
import { useRunsStore } from "../runsStore";
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

function runs(run: RunSnapshot): void {
  vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: {}, runs: [run] } as unknown as RunList);
}

describe("ActiveRunNotice", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    useRunsStore.setState({ byProject: {} });
  });

  it("warns on a page that edits media and leads to the run's controls, holding none itself", async () => {
    window.history.pushState({}, "", "/app/projects/demo/characters");
    runs(RUN);
    const control = vi.spyOn(client, "controlProductionRun");
    const card = document.createElement("summary");
    card.id = "run-controls";
    card.tabIndex = 0;
    card.scrollIntoView = vi.fn();
    document.body.appendChild(card);

    render(<ActiveRunNotice projectName="demo" />);
    expect(await screen.findByRole("status")).toHaveTextContent("第 2 集");
    expect(screen.queryByRole("button", { name: "暂停运行" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "查看并控制本次运行" }));
    expect(window.location.pathname).toBe("/app/projects/demo");
    expect(card.scrollIntoView).toHaveBeenCalled();
    expect(card).toHaveFocus();
    expect(control).not.toHaveBeenCalled();
    card.remove();
  });

  it("stays quiet on pages that change no media, and when the run has stopped", async () => {
    window.history.pushState({}, "", "/app/projects/demo");
    const list = vi
      .spyOn(client, "listProductionRuns")
      .mockResolvedValue({ start: {}, runs: [RUN] } as unknown as RunList);
    const { unmount } = render(<ActiveRunNotice projectName="demo" />);
    await vi.waitFor(() => expect(list).toHaveBeenCalled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    unmount();

    window.history.pushState({}, "", "/app/projects/demo/episodes/2");
    useRunsStore.setState({ byProject: {} });
    runs({ ...RUN, status: "BLOCKED_CONFIGURATION" } as RunSnapshot);
    render(<ActiveRunNotice projectName="demo" />);
    await vi.waitFor(() => expect(useRunsStore.getState().byProject.demo).toBeDefined());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
