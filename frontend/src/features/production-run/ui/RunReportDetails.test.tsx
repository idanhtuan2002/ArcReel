import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

import * as client from "../api/productionRunClient";
import { RunReportDetails } from "./RunReportDetails";

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RunReportDetails", () => {
  it("shows each reviewer's verdict, scores and findings, and the accepted story issues", async () => {
    vi.spyOn(client, "getProductionRunReport").mockResolvedValue({
      run_id: "run-1",
      quality: [
        {
          target: "episode:1",
          reviews: [
            {
              role: "reviewer_a",
              model_identity: "ollama/qwen2.5vl:7b@sha256:abc",
              outcome: "COMPLETED",
              accepted: false,
              scores: { story: 5, visual: 3, audio: 5, continuity: 4, pacing: 4 },
              findings: [{ code: "SUBTITLE_DRIFT", severity: "MINOR", detail: "lệch phụ đề" }],
            },
          ],
        },
      ],
      story_exceptions: [
        { code: "NO_ENDING", severity: "NARRATIVE_CRITICAL", node_id: "scene_draft[3,3]", message: "chưa kết", quote: "" },
      ],
    });
    render(<RunReportDetails projectName="alpha" runId="run-1" version={4} />);

    fireEvent.click(await screen.findByText("Quality review"));
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("ollama/qwen2.5vl:7b")).toBeInTheDocument();
    expect(screen.getByText("Story 5 · Picture 3 · Audio 5 · Continuity 4 · Pacing 4")).toBeInTheDocument();
    expect(screen.getByText("MINOR · SUBTITLE_DRIFT: lệch phụ đề")).toBeInTheDocument();
    expect(screen.getByText("Story issues accepted automatically (1)")).toBeInTheDocument();
  });

  it("shows nothing for a run that has not reached review or the story commit", async () => {
    const report = vi
      .spyOn(client, "getProductionRunReport")
      .mockResolvedValue({ run_id: "run-1", quality: [], story_exceptions: [] });
    const { container } = render(<RunReportDetails projectName="alpha" runId="run-1" version={2} />);

    await vi.waitFor(() => expect(report).toHaveBeenCalledTimes(1));
    expect(container).toBeEmptyDOMElement();
  });

  it("previews each verified final", async () => {
    vi.spyOn(client, "getProductionRunReport").mockResolvedValue({
      run_id: "run-1",
      quality: [],
      story_exceptions: [],
      previews: [{ target: "episode:1" }],
    });
    const preview = vi.spyOn(client, "previewProductionFinal").mockResolvedValue(new Blob(["mp4"]));
    vi.stubGlobal("URL", { ...URL, createObjectURL: () => "blob:final", revokeObjectURL: () => undefined });
    render(<RunReportDetails projectName="alpha" runId="run-1" version={4} />);

    fireEvent.click(await screen.findByRole("button", { name: "Watch the final of episode 1" }));

    expect(await screen.findByLabelText("Final of episode 1")).toHaveAttribute("src", "blob:final");
    expect(preview).toHaveBeenCalledWith("alpha", "run-1", 1);
    vi.unstubAllGlobals();
  });

  it("names the final a review is deciding on and fetches it anew after a rework", async () => {
    vi.spyOn(client, "getProductionRunReport").mockResolvedValue({
      run_id: "run-1",
      quality: [],
      story_exceptions: [],
      previews: [{ target: "episode:1", pending: true }],
    });
    const preview = vi.spyOn(client, "previewProductionFinal").mockResolvedValue(new Blob(["mp4"]));
    vi.stubGlobal("URL", { ...URL, createObjectURL: () => "blob:pending", revokeObjectURL: () => undefined });
    const { rerender } = render(<RunReportDetails projectName="alpha" runId="run-1" version={7} />);

    fireEvent.click(await screen.findByRole("button", { name: "Watch the final awaiting review (episode 1)" }));
    expect(await screen.findByLabelText("Final of episode 1")).toHaveAttribute("src", "blob:pending");

    rerender(<RunReportDetails projectName="alpha" runId="run-1" version={9} />);

    expect(
      await screen.findByRole("button", { name: "Watch the final awaiting review (episode 1)" }),
    ).toBeInTheDocument();
    expect(preview).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });
});
