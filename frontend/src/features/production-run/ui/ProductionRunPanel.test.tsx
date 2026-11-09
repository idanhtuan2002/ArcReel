import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api";
import i18n from "@/i18n";

import { API } from "@/api";
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

beforeEach(() => {
  vi.spyOn(client, "getProductionRunReport").mockResolvedValue({ run_id: "run-1", quality: [], story_exceptions: [] });
  vi.spyOn(client, "getProductionRunProgress").mockResolvedValue({ run_id: "run-1", stage: "STORY", tasks: {} });
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
      targets: ["episode:1"],
      expected_input_digest: "sha256:in",
      policy_digest: "sha256:auto",
    });
    resolve(snapshot());
    expect(await screen.findByText("Stage: Story")).toBeInTheDocument();
  });

  it("starts from the project's own story without an idea", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: OFFER, runs: [] });
    const startProductionRun = vi.spyOn(client, "startProductionRun").mockResolvedValue(snapshot());
    render(<ProductionRunPanel projectName="alpha" />);
    fireEvent.click(await screen.findByLabelText("From the story in this project"));
    expect(screen.queryByPlaceholderText("One or two sentences about the story")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    expect(startProductionRun).toHaveBeenCalledTimes(1);
    const command = startProductionRun.mock.calls[0][1];
    expect(command).toMatchObject({ story_source: "project", targets: ["episode:1"] });
    expect(command).not.toHaveProperty("idea");
  });

  it("starts a novel from an idea with its chapter count", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: OFFER, runs: [] });
    const startProductionRun = vi.spyOn(client, "startProductionRun").mockResolvedValue(snapshot());
    render(<ProductionRunPanel projectName="alpha" />);
    fireEvent.change(await screen.findByPlaceholderText("One or two sentences about the story"), {
      target: { value: "Chuyến đò cuối." },
    });
    fireEvent.click(screen.getByLabelText("Novel (many chapters, written part by part)"));
    fireEvent.change(screen.getByLabelText("Chapters"), { target: { value: "5" } });
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Chapters"), { target: { value: "40" } });
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    expect(startProductionRun.mock.calls[0][1]).toMatchObject({ idea: "Chuyến đò cuối.", book_chapters: 40 });
  });

  it("names the book's next part when continuing a novel project", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: OFFER, runs: [] });
    vi.spyOn(API, "request").mockResolvedValue({
      book: { spec: { chapters: 30, part_chapters: 5, chapter_syllables: 3000 }, parts_done: 2, parts_total: 6 },
    } as never);
    render(<ProductionRunPanel projectName="alpha" />);
    fireEvent.click(await screen.findByLabelText("Continue the story in this project"));
    expect(await screen.findByText(/continuing writes part 3 of 6/)).toBeInTheDocument();
  });

  it("starts a variant of another project's story with a named profile", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: OFFER, runs: [] });
    vi.spyOn(API, "listProjects").mockResolvedValue({
      projects: [
        { name: "alpha", title: "Alpha" },
        { name: "origin", title: "Truyện gốc" },
      ],
    } as never);
    vi.spyOn(API, "request").mockResolvedValue({
      profiles: [{ id: "first-person", label: "Ngôi thứ nhất", instruction: "Kể ở ngôi thứ nhất." }],
    } as never);
    const startProductionRun = vi.spyOn(client, "startProductionRun").mockResolvedValue(snapshot());
    render(<ProductionRunPanel projectName="alpha" />);
    fireEvent.click(await screen.findByLabelText("A variant of another project's story"));
    const button = screen.getByRole("button", { name: "Start" });
    expect(button).toBeDisabled();
    fireEvent.change(await screen.findByLabelText("Story from"), { target: { value: "origin" } });
    await screen.findByRole("option", { name: "Ngôi thứ nhất" });
    fireEvent.change(screen.getByLabelText("Variant profile"), { target: { value: "first-person" } });
    expect(screen.queryByRole("option", { name: "Alpha" })).not.toBeInTheDocument();
    fireEvent.click(button);

    expect(startProductionRun.mock.calls[0][1]).toMatchObject({
      story_source: "variant",
      source_project: "origin",
      variant_profile: "first-person",
    });
    expect(startProductionRun.mock.calls[0][1]).not.toHaveProperty("idea");
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

  it("offers rework from pictures and voice only at the final film review", async () => {
    const pending = snapshot({
      status: "WAITING_REVIEW",
      stage: "QUALITY",
      policy: { mode: "semi" },
      pending_review: { checkpoint: "FINAL_FILM", binding_digest: "sha256:final" },
    });
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: OFFER, runs: [pending] });
    const review = vi.spyOn(client, "reviewProductionRun").mockResolvedValue(snapshot({ stage: "MEDIA", generation: 2 }));
    render(<ProductionRunPanel projectName="alpha" />);

    fireEvent.click(await screen.findByRole("button", { name: "Rework from pictures & voice" }));

    await waitFor(() => expect(review).toHaveBeenCalledTimes(1));
    expect(review.mock.calls[0][2]).toMatchObject({
      checkpoint: "FINAL_FILM",
      binding_digest: "sha256:final",
      decision: "REWORK",
    });
  });

  it("does not offer rework before the final film", async () => {
    const pending = snapshot({
      status: "WAITING_REVIEW",
      stage: "SCRIPT",
      policy: { mode: "semi" },
      pending_review: { checkpoint: "SCRIPT_PACKAGE", binding_digest: "sha256:bind" },
    });
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: OFFER, runs: [pending] });
    render(<ProductionRunPanel projectName="alpha" />);

    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rework from pictures & voice" })).not.toBeInTheDocument();
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

    expect(await screen.findByText("Reason: the budget is used up")).toBeInTheDocument();
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
    expect(steps.querySelectorAll("li")).toHaveLength(15);
    expect(steps.querySelector("[aria-current='step']")?.textContent).toBe("Pictures & voice");
    expect(screen.getByText("Status: Working")).toBeInTheDocument();
  });

  it("starts the chosen number of episodes when the project allows more than one", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({
      start: { ...OFFER, max_target_episodes: 3 },
      runs: [],
    });
    const start = vi.spyOn(client, "startProductionRun").mockResolvedValue(snapshot());
    render(<ProductionRunPanel projectName="alpha" />);
    fireEvent.change(await screen.findByPlaceholderText("One or two sentences about the story"), {
      target: { value: "Chuyến đò cuối." },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Episodes" }), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    expect(start.mock.calls[0][1].targets).toEqual(["episode:1", "episode:2"]);
  });

  it("switches a stopped run to the other mode with that mode's policy digest", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({
      start: OFFER,
      runs: [snapshot({ status: "PAUSED" })],
    });
    const change = vi.spyOn(client, "changeProductionRunMode").mockResolvedValue(snapshot({ status: "PAUSED" }));
    render(<ProductionRunPanel projectName="alpha" />);

    fireEvent.click(await screen.findByRole("button", { name: "Switch to semi-automatic" }));

    await waitFor(() => expect(change).toHaveBeenCalledTimes(1));
    expect(change.mock.calls[0][2]).toMatchObject({ mode: "semi", policy_digest: "sha256:semi", expected_version: 3 });
  });

  it("names a refused command and its reasons", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: OFFER, runs: [] });
    vi.spyOn(client, "startProductionRun").mockRejectedValue(
      new ApiRequestError("failed", undefined, 409, "PREFLIGHT_BLOCKED", {
        code: "PREFLIGHT_BLOCKED",
        reasons: ["REVIEWER_NOT_QUALIFIED"],
      }),
    );
    render(<ProductionRunPanel projectName="alpha" />);
    fireEvent.change(await screen.findByPlaceholderText("One or two sentences about the story"), {
      target: { value: "Chuyến đò cuối." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    expect(
      await screen.findByText("The request failed: The run cannot start yet (a reviewer model is not qualified)"),
    ).toBeInTheDocument();
  });

  it("follows the newest run and lets an earlier one be opened with its details", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({
      start: OFFER,
      runs: [
        snapshot({ run_id: "run-2", status: "RUNNING", stage: "MEDIA", created_at: "2026-11-03T00:00:00Z" }),
        snapshot({
          run_id: "run-1",
          status: "FAILED_QUALITY",
          stage: "QUALITY",
          generation: 2,
          final_evaluations: 2,
          repair_counts: [{ stage: "MEDIA", unit_key: "episode:1", count: 1 }],
        }),
      ],
    });
    const { container } = render(<ProductionRunPanel projectName="alpha" />);

    await waitFor(() => expect(container.querySelector("[data-run-id='run-2']")).toBeTruthy());
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Run" }), { target: { value: "run-1" } });

    expect(container.querySelector("[data-run-id='run-1']")).toBeTruthy();
    expect(screen.getByText(/Generation 2 · Quality reviews 2\/3 · Pictures & voice redone 1×/)).toBeInTheDocument();
  });

  it("counts the current stage's tasks while the run is active", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({
      start: OFFER,
      runs: [snapshot({ status: "WAITING_TASK", stage: "MEDIA" })],
    });
    vi.spyOn(client, "getProductionRunProgress").mockResolvedValue({
      run_id: "run-1",
      stage: "MEDIA",
      tasks: { running: 1, queued: 4, succeeded: 12, failed: 1 },
    });
    render(<ProductionRunPanel projectName="alpha" />);

    expect(
      await screen.findByText("Tasks of this stage: 1 running · 4 queued · 12 done · 1 failed"),
    ).toBeInTheDocument();
  });

  it("shows the pictures and clips the current stage has made as thumbnails", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({
      start: OFFER,
      runs: [snapshot({ status: "WAITING_TASK", stage: "MEDIA" })],
    });
    vi.spyOn(client, "getProductionRunProgress").mockResolvedValue({
      run_id: "run-1",
      stage: "MEDIA",
      tasks: { running: 1, succeeded: 3 },
      media: [
        { task_id: "t1", media_type: "image", resource_type: "storyboards", resource_id: "E1S01", file_path: "storyboards/scene_E1S01.png", version: 2 },
        { task_id: "t2", media_type: "video", resource_type: "videos", resource_id: "E1S02", file_path: "videos/scene_E1S02.mp4", version: null },
        { task_id: "t3", media_type: "audio", resource_type: "audio", resource_id: "E1S01", file_path: "audio/E1S01.wav", version: 1 },
      ],
    });
    render(<ProductionRunPanel projectName="alpha" />);

    const list = await screen.findByRole("list", { name: "Pictures and clips made in this stage" });
    expect(list.querySelectorAll("li")).toHaveLength(2);
    expect(screen.getByRole("img", { name: "E1S01 · storyboards" })).toHaveAttribute(
      "src",
      expect.stringContaining("/files/alpha/storyboards/scene_E1S01.png?v=2"),
    );
    expect(screen.getByText("Made so far: 2 pictures and clips · 1 voice files")).toBeInTheDocument();
  });

  it("shows the run as a read-only graph only once the owner opens it", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({
      start: OFFER,
      runs: [snapshot({ status: "WAITING_TASK", stage: "MEDIA" })],
    });
    render(<ProductionRunPanel projectName="alpha" />);

    const summary = await screen.findByText("Show as a graph");
    expect(screen.queryByLabelText("Run graph")).not.toBeInTheDocument();
    const details = summary.closest("details") as HTMLDetailsElement;
    details.open = true;
    fireEvent(details, new Event("toggle"));

    expect(await screen.findByLabelText("Run graph")).toBeInTheDocument();
  });

  it("shows how far the story is written while the run is in STORY", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: OFFER, runs: [snapshot()] });
    vi.spyOn(client, "getProductionRunProgress").mockResolvedValue({
      run_id: "run-1",
      stage: "STORY",
      tasks: {},
      story: {
        phase: "RUNNING",
        planning_done: 7,
        planning_total: 7,
        scenes_drafted: 6,
        scenes_planned: 10,
        reviews_done: 1,
        reviews_total: 5,
        generate_calls: 120,
        generate_calls_max: 300,
      },
    });
    render(<ProductionRunPanel projectName="alpha" />);

    expect(
      await screen.findByText("Writing the story: planning 7/7 · scenes 6/10 · reviews 1/5 · model calls 120/300"),
    ).toBeInTheDocument();
  });

  it("names each passed stage's duration and the run's total time once it has finished", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({
      start: OFFER,
      runs: [snapshot({ status: "SUCCEEDED", stage: "EXPORT" })],
    });
    vi.spyOn(client, "getProductionRunProgress").mockResolvedValue({
      run_id: "run-1",
      stage: "EXPORT",
      started_at: "2026-11-01T00:00:00Z",
      stages: [
        { stage: "BRIEF", finished_at: "2026-11-01T00:00:45Z" },
        { stage: "STORY", finished_at: "2026-11-01T04:10:45Z" },
        { stage: "EXPORT", finished_at: "2026-11-01T04:33:00Z" },
      ],
      tasks: {},
    });
    render(<ProductionRunPanel projectName="alpha" />);

    const steps = await screen.findByRole("list", { name: "Steps" });
    await waitFor(() => expect(steps).toHaveTextContent(/· 4h 10m/));
    expect(steps).toHaveTextContent(/· 45s/);
    expect(steps).toHaveTextContent(/· 22m/);
    expect(screen.getByText(/elapsed 4h 33m/)).toBeInTheDocument();
  });

  it("filters earlier runs by status and names a stop in an alert with a copy action", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({
      start: OFFER,
      runs: [
        snapshot({ run_id: "run-3", status: "BLOCKED_BUDGET", reason: "BUDGET_EXHAUSTED" }),
        snapshot({ run_id: "run-2", status: "SUCCEEDED", stage: "EXPORT" }),
        snapshot({ run_id: "run-1", status: "FAILED_QUALITY", stage: "QUALITY" }),
      ],
    });
    render(<ProductionRunPanel projectName="alpha" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Reason: the budget is used up");
    expect(screen.getByRole("button", { name: "Copy error" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Failed (1)" }));

    const options = screen.getAllByRole("option").map((option) => option.getAttribute("value"));
    expect(options).toEqual(["run-3", "run-1"]);
  });

  it("fills the idea from an example", async () => {
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: OFFER, runs: [] });
    render(<ProductionRunPanel projectName="alpha" />);

    fireEvent.click(await screen.findByRole("button", { name: "Last ferry" }));

    expect(screen.getByPlaceholderText("One or two sentences about the story")).toHaveValue(
      "On the last ferry before the bridge opens, an old boatman takes one more passenger across the river.",
    );
  });
});
