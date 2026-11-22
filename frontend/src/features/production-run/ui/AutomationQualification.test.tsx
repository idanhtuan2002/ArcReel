import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

import * as client from "../api/productionRunClient";
import type { QualificationStatus } from "../api/types";
import { AutomationQualification } from "./AutomationQualification";

function status(changes: Partial<QualificationStatus> = {}): QualificationStatus {
  return {
    receipts_configured: true,
    evidence_configured: true,
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
  it("asks nothing of reviewers: they are trusted by configuration", async () => {
    vi.spyOn(client, "getQualification").mockResolvedValue(status());
    await open();

    expect(
      await screen.findByText(/Reviewers need no qualification/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Qualify reviewers" })).not.toBeInTheDocument();
  });

  it("records the launch, or names what still blocks it", async () => {
    vi.spyOn(client, "getQualification").mockResolvedValue(status());
    const record = vi
      .spyOn(client, "recordLaunchQualification")
      .mockResolvedValueOnce({ recorded: false, reasons: ["MISSING_PUBLISHED_PROFILE"] })
      .mockResolvedValueOnce({ recorded: true, reasons: [] });
    const onChanged = await open();

    fireEvent.click(await screen.findByRole("button", { name: "Record launch qualification" }));
    expect(await screen.findByText("Not recorded; first resolve: no published quality profile")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Record launch qualification" }));

    expect(await screen.findByText("Launch qualification recorded.")).toBeInTheDocument();
    expect(record).toHaveBeenCalledTimes(2);
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("explains a server without probe receipts and keeps the probe button off", async () => {
    const media = [
      { role: "video", provider_id: "custom-8", model_id: "cloud-video", profile_route: false, probe: null, job: null },
    ];
    vi.spyOn(client, "getQualification").mockResolvedValue(status({ receipts_configured: false, media }));
    await open();

    expect(await screen.findByRole("button", { name: "Try media routes" })).toBeDisabled();
    expect(screen.getByText(/no probe receipt folder/)).toBeInTheDocument();
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
