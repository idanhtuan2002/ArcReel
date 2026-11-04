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
});
