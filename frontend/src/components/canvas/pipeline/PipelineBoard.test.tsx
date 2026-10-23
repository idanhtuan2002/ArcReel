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

  it("shows the Human gates with their latest decision and a missing video provider", () => {
    const { hook } = memoryLocation({ path: "/" });
    const decision = (action: string) => ({
      decision_id: action,
      action,
      sequence: 1,
      created_at: "2026-10-22T10:00:00Z",
      authorization: { authenticated_principal: "admin", authorized_at: "" },
    });
    render(
      <Router hook={hook}>
        <PipelineBoardView
          plan={null}
          runs={[]}
          gates={{ greenlight: [decision("GREENLIGHT")], script_lock: [], publish_approval: [] }}
          videoReady={false}
        />
      </Router>,
    );
    const gates = screen.getByRole("list", { name: "审批关卡（始终由你决定）" });
    expect(within(gates).getAllByRole("listitem")).toHaveLength(4);
    expect(within(gates).getByText(/A · /).closest("li")).toHaveTextContent("已批准");
    expect(within(gates).getByText(/B · /).closest("li")).toHaveTextContent("尚无");
    expect(screen.getByText(/尚未配置视频供应商/)).toBeInTheDocument();
  });
});

