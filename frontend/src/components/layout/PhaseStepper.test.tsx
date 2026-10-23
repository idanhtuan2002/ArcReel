import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NORTH_STAR_STAGES, PhaseStepper, stageForPhase } from "./PhaseStepper";

describe("PhaseStepper on the North Star loop", () => {
  it("maps the server project phase onto a North Star stage", () => {
    expect(stageForPhase("preparation")).toBe("create");
    expect(stageForPhase("script")).toBe("adapt");
    expect(stageForPhase("production")).toBe("produce");
    expect(stageForPhase("completed")).toBe("package");
    expect(stageForPhase(undefined)).toBeNull();
  });

  it("shows every stage, labels the current one and marks stages without a surface as coming soon", () => {
    render(<PhaseStepper currentPhase="script" />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(NORTH_STAR_STAGES.length);
    const current = items.find((item) => item.getAttribute("aria-current") === "step");
    expect(current).toHaveTextContent("剧本");
    expect(items[0]).toHaveAttribute("data-state", "soon");
    expect(items[0]).toHaveAccessibleName(/发现.*即将推出/);
    expect(items[2]).toHaveAttribute("data-state", "done");
    expect(items[4]).toHaveAttribute("data-state", "todo");
  });

  it("shows no current stage when the server reports no phase", () => {
    render(<PhaseStepper currentPhase={undefined} />);
    expect(screen.getAllByRole("listitem").some((item) => item.getAttribute("aria-current") === "step")).toBe(false);
  });
});
