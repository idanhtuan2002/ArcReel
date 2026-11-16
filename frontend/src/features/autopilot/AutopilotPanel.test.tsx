import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

const { getAutopilot, getProductionRun, resumeProductionRun } = vi.hoisted(() => ({
  getAutopilot: vi.fn(),
  getProductionRun: vi.fn(),
  resumeProductionRun: vi.fn(),
}));

vi.mock("./autopilotClient", () => ({ getAutopilot, setAutopilot: vi.fn() }));
vi.mock("@/features/production-run/api/productionRunClient", () => ({
  getProductionRun,
  resumeProductionRun,
  newCommandId: () => "cmd-1",
}));

import { AutopilotPanel } from "./AutopilotPanel";

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

describe("autopilot panel of a halted run", () => {
  it("resumes the run from the panel as it is now", async () => {
    getAutopilot.mockResolvedValue({
      available: true,
      delegation: { state: "ENABLED", story: { book_chapters: 30 } },
      status: { state: "halted", run_id: "run-1", reason: "OUTCOME_UNKNOWN" },
    });
    getProductionRun.mockResolvedValue({ version: 7, input_digest: "sha256:i", policy_digest: "sha256:p" });
    resumeProductionRun.mockResolvedValue({});

    render(<AutopilotPanel projectName="p" kind="story" />);
    fireEvent.click(await screen.findByRole("button", { name: "Resume" }));

    await waitFor(() =>
      expect(resumeProductionRun).toHaveBeenCalledWith(
        "p",
        { version: 7, input_digest: "sha256:i", policy_digest: "sha256:p" },
        "cmd-1",
      ),
    );
  });
});
