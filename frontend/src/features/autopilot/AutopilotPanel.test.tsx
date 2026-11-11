import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

const { getAutopilot, getProductionRun, controlProductionRun } = vi.hoisted(() => ({
  getAutopilot: vi.fn(),
  getProductionRun: vi.fn(),
  controlProductionRun: vi.fn(),
}));

vi.mock("./autopilotClient", () => ({ getAutopilot, setAutopilot: vi.fn() }));
vi.mock("@/features/production-run/api/productionRunClient", () => ({
  getProductionRun,
  controlProductionRun,
  newCommandId: () => "cmd-1",
}));

import { AutopilotPanel } from "./AutopilotPanel";

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

describe("autopilot panel of a halted run", () => {
  it("resumes the run from the panel with the run's current version", async () => {
    getAutopilot.mockResolvedValue({
      available: true,
      delegation: { state: "ENABLED", story: { book_chapters: 30 } },
      status: { state: "halted", run_id: "run-1", reason: "OUTCOME_UNKNOWN" },
    });
    getProductionRun.mockResolvedValue({ version: 7, input_digest: "sha256:i", policy_digest: "sha256:p" });
    controlProductionRun.mockResolvedValue({});

    render(<AutopilotPanel projectName="p" kind="story" />);
    fireEvent.click(await screen.findByRole("button", { name: "Resume" }));

    await waitFor(() =>
      expect(controlProductionRun).toHaveBeenCalledWith("p", "run-1", "resume", {
        command_id: "cmd-1",
        expected_version: 7,
        expected_input_digest: "sha256:i",
        policy_digest: "sha256:p",
      }),
    );
  });
});
