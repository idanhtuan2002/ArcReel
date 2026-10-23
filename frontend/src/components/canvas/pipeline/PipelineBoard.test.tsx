import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";

import { PipelineBoardView } from "./PipelineBoard";

describe("PipelineBoardView", () => {
  it("shows every loop stage, the coming-soon stages and the decisions waiting for the Human", () => {
    const { hook } = memoryLocation({ path: "/" });
    render(
      <Router hook={hook}>
        <PipelineBoardView
          plan={null}
          runs={[
            { run_id: "a", phase: "READY_FOR_APPROVAL", idea: "Ông Tư lái đò", genre: "g", started_at: "" },
            { run_id: "b", phase: "RUNNING", idea: "Cô giáo bản", genre: "g", started_at: "" },
          ]}
        />
      </Router>,
    );
    const stages = screen.getAllByRole("listitem").filter((item) => item.hasAttribute("data-state"));
    expect(stages).toHaveLength(10);
    expect(stages[0]).toHaveAttribute("data-state", "soon");
    expect(stages[2]).toHaveAttribute("data-state", "active");
    const links = screen.getAllByRole("link").map((link) => link.textContent);
    expect(links.some((text) => text?.includes("Ông Tư lái đò"))).toBe(true);
    expect(links.some((text) => text?.includes("Cô giáo bản"))).toBe(true);
    expect(within(stages[0]).queryByRole("link")).not.toBeInTheDocument();
  });
});
