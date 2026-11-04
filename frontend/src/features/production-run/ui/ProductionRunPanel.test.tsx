import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

import * as client from "../api/productionRunClient";
import type { RunList, RunSnapshot } from "../api/types";
import { ProductionRunPanel } from "./ProductionRunPanel";

const OFFER = {
  enabled: true,
  input_digest: "sha256:in",
  policy_digests: { auto: "sha256:auto", semi: "sha256:semi" },
};

function snapshot(changes: Partial<RunSnapshot> = {}): RunSnapshot {
  return {
    user_id: "u",
    project_name: "alpha",
    run_id: "run-1",
    status: "RUNNING",
    stage: "STORY",
    generation: 1,
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
  };
}

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ProductionRunPanel", () => {
  it("defaultsToAutoAndStartsOnce", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: OFFER, runs: [] });
    let resolve: (value: RunSnapshot) => void = () => {};
    const startProductionRun = vi
      .spyOn(client, "startProductionRun")
      .mockReturnValue(new Promise<RunSnapshot>((done) => (resolve = done)));
    render(<ProductionRunPanel projectName="alpha" />);
    fireEvent.change(await screen.findByPlaceholderText("One or two sentences about the story"), {
      target: { value: "Chuyến đò cuối." },
    });
    const button = screen.getByRole("button", { name: "Start" });
    fireEvent.click(button);
    fireEvent.click(button);

    expect(startProductionRun).toHaveBeenCalledTimes(1);
    expect(startProductionRun.mock.calls[0][1]).toMatchObject({
      mode: "auto",
      idea: "Chuyến đò cuối.",
      expected_input_digest: "sha256:in",
      policy_digest: "sha256:auto",
    });
    resolve(snapshot());
    expect(await screen.findByText("Stage: Story")).toBeInTheDocument();
  });

  it("shows exactly the pending semi checkpoint and sends its binding", async () => {
    const pending = snapshot({
      status: "WAITING_REVIEW",
      stage: "SCRIPT",
      policy: { mode: "semi" },
      pending_review: { checkpoint: "SCRIPT_PACKAGE", binding_digest: "sha256:bind" },
    });
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: OFFER, runs: [pending] });
    const review = vi.spyOn(client, "reviewProductionRun").mockResolvedValue(snapshot({ stage: "MEDIA" }));
    render(<ProductionRunPanel projectName="alpha" />);

    expect(await screen.findByText("Review needed: script package")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(review).toHaveBeenCalledTimes(1));
    expect(review.mock.calls[0][2]).toMatchObject({
      checkpoint: "SCRIPT_PACKAGE",
      binding_digest: "sha256:bind",
      decision: "APPROVE",
      expected_version: 3,
    });
  });

  it("ignoresPreviousProjectResponse", async () => {
    let late: (value: RunList) => void = () => {};
    vi.spyOn(client, "listProductionRuns").mockImplementation((projectName) =>
      projectName === "alpha"
        ? new Promise<RunList>((done) => (late = done))
        : Promise.resolve({ start: OFFER, runs: [snapshot({ project_name: "beta", run_id: "run-beta" })] }),
    );
    const { rerender, container } = render(<ProductionRunPanel key="alpha" projectName="alpha" />);
    rerender(<ProductionRunPanel key="beta" projectName="beta" />);
    await waitFor(() => expect(container.querySelector("[data-run-id='run-beta']")).toBeTruthy());

    late({ start: OFFER, runs: [snapshot()] });
    await new Promise((done) => setTimeout(done, 0));

    expect(container.querySelector("[data-run-id='run-1']")).toBeNull();
  });

  it("names the blocked reason and offers resume, not routine continue prompts", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({
      start: OFFER,
      runs: [snapshot({ status: "BLOCKED_BUDGET", reason: "BUDGET_EXHAUSTED" })],
    });
    render(<ProductionRunPanel projectName="alpha" />);

    expect(await screen.findByText("Reason: BUDGET_EXHAUSTED")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
  });

  it("offers the private archive of a succeeded run", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({
      start: OFFER,
      runs: [
        snapshot({
          status: "SUCCEEDED",
          stage: "EXPORT",
          completed_targets: [
            {
              target: "episode:1",
              archive_digest: "sha256:a",
              archive_size: 1_000_000,
              final_digest: "sha256:f",
              quality_decision: "PASS",
            },
          ],
        }),
      ],
    });
    render(<ProductionRunPanel projectName="alpha" />);

    expect(await screen.findByRole("button", { name: "Download episode 1" })).toBeInTheDocument();
    expect(screen.getByText("Passed quality review")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("marks an exported final the reviewers rejected as not passed", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({
      start: OFFER,
      runs: [
        snapshot({
          status: "SUCCEEDED",
          stage: "EXPORT",
          completed_targets: [
            {
              target: "episode:1",
              archive_digest: "sha256:a",
              archive_size: 2_500_000,
              final_digest: "sha256:f",
              quality_decision: "REWORK",
            },
          ],
        }),
      ],
    });
    render(<ProductionRunPanel projectName="alpha" />);

    expect(await screen.findByText("Not passed: best version exported")).toBeInTheDocument();
    expect(screen.getByText("2.5 MB")).toBeInTheDocument();
  });

  it("names the stages and marks the current one", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({
      start: { enabled: false, reason: "RELEASE_GATE_PENDING" },
      runs: [snapshot({ status: "WAITING_TASK", stage: "MEDIA" })],
    });
    render(<ProductionRunPanel projectName="alpha" />);

    const steps = await screen.findByRole("list", { name: "Steps" });
    expect(steps.querySelectorAll("li")).toHaveLength(14);
    expect(steps.querySelector("[aria-current='step']")?.textContent).toBe("Pictures & voice");
    expect(screen.getByText("Status: Working")).toBeInTheDocument();
  });
});
