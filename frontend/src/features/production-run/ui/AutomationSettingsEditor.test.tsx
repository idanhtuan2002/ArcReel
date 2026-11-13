import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api";
import i18n from "@/i18n";

import * as client from "../api/productionRunClient";
import type { AutomationRole, AutomationSettings, ModelOption } from "../api/types";
import { AutomationSettingsEditor } from "./AutomationSettingsEditor";

const ROLES: AutomationRole[] = ["writer", "script", "reviewer_a", "reviewer_b", "image", "video", "audio"];
const LOCAL: ModelOption = { provider_id: "custom-1", model_id: "local-m", label: "Ollama · local-m", local: true };
const CLOUD: ModelOption = { provider_id: "custom-4", model_id: "gemini-3.6-flash", label: "Gemini · 3.6", local: false };

function loaded(): AutomationSettings {
  return {
    settings: {
      configured: true,
      has_quality_profile: true,
      launch_profile_id: "fiction_narration_vi_v1",
      routes: ROLES.map((role) => ({ role, provider_id: "custom-1", model_id: "local-m" })),
      max_target_episodes: 1,
    },
    options: Object.fromEntries(ROLES.map((role) => [role, [LOCAL, CLOUD]])) as AutomationSettings["options"],
    launch_profiles: ["fiction_narration_vi_v1"],
    quality_profiles: [
      { profile_id: "auto-review", revision: 2, profile_digest: "sha256:p", automatic: true },
      { profile_id: "human-review", revision: 1, profile_digest: "sha256:h", automatic: false },
    ],
  };
}

async function open() {
  const { container } = render(<AutomationSettingsEditor projectName="alpha" />);
  const details = container.querySelector("details");
  if (!details) throw new Error("no details");
  details.open = true;
  fireEvent(details, new Event("toggle"));
  return screen.findByRole("button", { name: "Save setup" });
}

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AutomationSettingsEditor", () => {
  it("saves a cloud reviewer with its per-call ceiling and the run limits", async () => {
    vi.spyOn(client, "getAutomationSettings").mockResolvedValue(loaded());
    const save = vi.spyOn(client, "saveAutomationSettings").mockResolvedValue(loaded().settings);
    const button = await open();

    fireEvent.change(screen.getByRole("combobox", { name: "Reviewer B" }), {
      target: { value: "custom-4/gemini-3.6-flash" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Max cost per call for Reviewer B" }), {
      target: { value: "5" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Episodes per run" }), { target: { value: "2" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Quality profile" }), { target: { value: "auto-review" } });
    fireEvent.click(button);

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    const update = save.mock.calls[0][1];
    expect(update.routes.find((route) => route.role === "reviewer_b")).toEqual({
      role: "reviewer_b",
      provider_id: "custom-4",
      model_id: "gemini-3.6-flash",
      max_cost_per_call: 5,
    });
    expect(update.max_target_episodes).toBe(2);
    expect(update.profile_id).toBe("auto-review");
    expect(await screen.findByRole("status")).toHaveTextContent("Saved.");
  });

  it("names a refusal from the server", async () => {
    vi.spyOn(client, "getAutomationSettings").mockResolvedValue(loaded());
    vi.spyOn(client, "saveAutomationSettings").mockRejectedValue(
      new ApiRequestError("refused", undefined, 422, "UNBOUNDED_PAID_ROUTE", { code: "UNBOUNDED_PAID_ROUTE" }),
    );
    fireEvent.click(await open());

    expect(await screen.findByRole("status")).toHaveTextContent("a paid model has no cost limit");
  });

  it("adds ordered fallback models to the writer, with a ceiling for a cloud one, and removes them", async () => {
    vi.spyOn(client, "getAutomationSettings").mockResolvedValue(loaded());
    const save = vi.spyOn(client, "saveAutomationSettings").mockResolvedValue(loaded().settings);
    const button = await open();

    const [addWriterFallback] = screen.getAllByRole("button", { name: "+ Add fallback" });
    fireEvent.click(addWriterFallback);
    const fallback = screen.getByRole("combobox", { name: "Fallback 1 for Writer" });
    expect(fallback).toHaveValue("custom-4/gemini-3.6-flash");
    fireEvent.change(screen.getByRole("spinbutton", { name: "Max cost per call for Fallback 1 for Writer" }), {
      target: { value: "3" },
    });
    fireEvent.click(button);

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save.mock.calls[0][1].fallbacks).toEqual([
      { role: "writer", provider_id: "custom-4", model_id: "gemini-3.6-flash", max_cost_per_call: 3 },
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Remove fallback 1" }));
    fireEvent.click(button);
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save.mock.calls[1][1].fallbacks).toEqual([]);
  });

  it("reorders fallbacks and makes one the default, the old default taking its place", async () => {
    const settings = loaded();
    const third: ModelOption = { provider_id: "custom-5", model_id: "glm", label: "BytePlus · glm", local: false };
    settings.options.writer = [LOCAL, CLOUD, third];
    settings.settings.fallbacks = [
      { role: "writer", provider_id: "custom-4", model_id: "gemini-3.6-flash", max_cost_per_call: 2 },
      { role: "writer", provider_id: "custom-5", model_id: "glm", max_cost_per_call: 4 },
    ];
    vi.spyOn(client, "getAutomationSettings").mockResolvedValue(settings);
    const save = vi.spyOn(client, "saveAutomationSettings").mockResolvedValue(settings.settings);
    const button = await open();

    fireEvent.click(screen.getByRole("button", { name: "Move fallback 2 up" }));
    fireEvent.click(screen.getByRole("button", { name: "Make fallback 1 the default model" }));
    fireEvent.click(button);

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    const update = save.mock.calls[0][1];
    expect(update.routes.find((route) => route.role === "writer")).toEqual({
      role: "writer",
      provider_id: "custom-5",
      model_id: "glm",
      max_cost_per_call: 4,
    });
    expect(update.fallbacks.map((route) => route.model_id)).toEqual(["local-m", "gemini-3.6-flash"]);
  });
});
