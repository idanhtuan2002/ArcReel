import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

import * as client from "../api/productionRunClient";
import type { QualificationStatus } from "../api/types";
import { AutomationQualification } from "./AutomationQualification";

function status(changes: Partial<QualificationStatus> = {}): QualificationStatus {
  return {
    corpus_configured: true,
    evidence_configured: true,
    reviewers: [
      { role: "reviewer_a", model_identity: "ollama/qwen2.5vl:7b@sha256:x", qualified: true, job: null },
      { role: "reviewer_b", model_identity: "ollama/gemma3:4b@sha256:y", qualified: false, job: null },
    ],
    launch_recorded: false,
    ...changes,
  };
}

async function open(onChanged = vi.fn()) {
  const { container } = render(<AutomationQualification projectName="alpha" onChanged={onChanged} />);
  const details = container.querySelector("details");
  if (!details) throw new Error("no details");
  details.open = true;
  fireEvent(details, new Event("toggle"));
  return onChanged;
}

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AutomationQualification", () => {
  it("shows each reviewer's state and starts a qualification job", async () => {
    vi.spyOn(client, "getQualification").mockResolvedValue(status());
    const start = vi.spyOn(client, "startReviewerQualification").mockResolvedValue(
      status({
        reviewers: [
          {
            role: "reviewer_b",
            model_identity: "ollama/gemma3:4b@sha256:y",
            qualified: false,
            job: {
              role: "reviewer_b",
              model_identity: "ollama/gemma3:4b@sha256:y",
              state: "running",
              done: 3,
              total: 40,
              qualified: null,
              error: null,
              started_at: "2026-11-04T00:00:00Z",
            },
          },
        ],
      }),
    );
    await open();

    expect(await screen.findByText("qualified")).toBeInTheDocument();
    expect(screen.getByText("not qualified")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Qualify reviewers" }));

    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("reviewing 3/40 cases")).toBeInTheDocument();
  });

  it("records the launch, or names what still blocks it", async () => {
    vi.spyOn(client, "getQualification").mockResolvedValue(status());
    const record = vi
      .spyOn(client, "recordLaunchQualification")
      .mockResolvedValueOnce({ recorded: false, reasons: ["MISSING_QUALIFIED_REVIEWER"] })
      .mockResolvedValueOnce({ recorded: true, reasons: [] });
    const onChanged = await open();

    fireEvent.click(await screen.findByRole("button", { name: "Record launch qualification" }));
    expect(await screen.findByText("Not recorded; first resolve: a reviewer model is not qualified")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Record launch qualification" }));

    expect(await screen.findByText("Launch qualification recorded.")).toBeInTheDocument();
    expect(record).toHaveBeenCalledTimes(2);
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("explains a server without a labeled corpus and keeps the job button off", async () => {
    vi.spyOn(client, "getQualification").mockResolvedValue(status({ corpus_configured: false }));
    await open();

    expect(await screen.findByRole("button", { name: "Qualify reviewers" })).toBeDisabled();
    expect(screen.getByText(/no labeled reviewer corpus/)).toBeInTheDocument();
  });

  it("lists media routes and probes the ones outside the profile", async () => {
    const media = [
      { role: "image", provider_id: "custom-3", model_id: "flux2", profile_route: true, probe: null, job: null },
      { role: "video", provider_id: "custom-8", model_id: "cloud-video", profile_route: false, probe: null, job: null },
      {
        role: "audio",
        provider_id: "custom-9",
        model_id: "cloud-voice",
        profile_route: false,
        probe: { passed: false, problem: "AUDIO_SILENT", error: null, recorded_at: "2026-11-08T00:00:00Z" },
        job: null,
      },
    ];
    vi.spyOn(client, "getQualification").mockResolvedValue(status({ media }));
    const probe = vi.spyOn(client, "startMediaProbes").mockResolvedValue(status({ media }));
    await open();

    expect(await screen.findByText("tested profile route")).toBeInTheDocument();
    expect(screen.getByText("not tried yet")).toBeInTheDocument();
    expect(screen.getByText("sample failed: AUDIO_SILENT")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try media routes" }));
    await waitFor(() => expect(probe).toHaveBeenCalledWith("alpha"));
  });
});
