import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

import * as client from "../api/productionRunClient";
import { AutomationReadiness } from "./AutomationReadiness";

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AutomationReadiness", () => {
  it("checks only when opened and names what blocks a start", async () => {
    const readiness = vi.spyOn(client, "getAutomationReadiness").mockResolvedValue({
      ready: false,
      reasons: ["MISSING_QUALIFIED_REVIEWER"],
      quality_gate: "record",
      routes: [
        {
          role: "reviewer_a",
          provider_id: "custom-4",
          model_id: "gemini-3.6-flash",
          model_identity: "gemini/gemini-3.6-flash",
          local: false,
          paid: true,
          max_cost_per_call: 5,
        },
      ],
      limits: {
        currency: "USD",
        max_cost_minor_units: 500,
        max_model_calls: 1500,
        max_tasks: 600,
        max_runtime_seconds: 64800,
        max_target_episodes: 1,
      },
    });
    const { container } = render(<AutomationReadiness projectName="alpha" />);
    expect(readiness).not.toHaveBeenCalled();

    const details = container.querySelector("details");
    if (!details) throw new Error("no details");
    details.open = true;
    fireEvent(details, new Event("toggle"));

    expect(await screen.findByText("Not ready to start:")).toBeInTheDocument();
    expect(screen.getByText("a reviewer model is not qualified")).toBeInTheDocument();
    expect(screen.getByText("Reviewer A")).toBeInTheDocument();
    expect(screen.getByText("paid, up to 5 per call")).toBeInTheDocument();
    expect(screen.getByText(/Limits: 1500 model calls, 18 h, 1 episode\(s\), cost 500 USD/)).toBeInTheDocument();
    expect(readiness).toHaveBeenCalledTimes(1);
  });
});
