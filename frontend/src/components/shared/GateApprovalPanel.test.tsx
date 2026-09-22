import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { GateApprovalPanel } from "./GateApprovalPanel";
import { useAppStore } from "@/stores/app-store";

describe("GateApprovalPanel", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.restoreAllMocks();
  });

  it("loads gate history and shows recorded decisions", async () => {
    vi.spyOn(API, "getGateHistory").mockResolvedValueOnce({
      greenlight: [
        {
          decision_id: "d-1",
          action: "GREENLIGHT",
          sequence: 1,
          created_at: "2026-09-22T00:00:00Z",
          authorization: { authenticated_principal: "operator-1", authorized_at: "2026-09-22T00:00:00Z" },
          source_digest: "sha256:a",
        },
      ],
      publish_approval: [],
    });

    render(<GateApprovalPanel projectName="demo" />);

    await waitFor(() => {
      expect(screen.getByText("已记录 1 条决策")).toBeInTheDocument();
    });
  });

  it("greenlights a project and refreshes history", async () => {
    vi.spyOn(API, "getGateHistory")
      .mockResolvedValueOnce({ greenlight: [], publish_approval: [] })
      .mockResolvedValueOnce({
        greenlight: [
          {
            decision_id: "d-1",
            action: "GREENLIGHT",
            sequence: 1,
            created_at: "2026-09-22T00:00:00Z",
            authorization: { authenticated_principal: "operator-1", authorized_at: "2026-09-22T00:00:00Z" },
            source_digest: "sha256:a",
          },
        ],
        publish_approval: [],
      });
    const greenlightSpy = vi.spyOn(API, "greenlightProject").mockResolvedValueOnce({
      decision_id: "d-1",
      action: "GREENLIGHT",
      sequence: 1,
      created_at: "2026-09-22T00:00:00Z",
      authorization: { authenticated_principal: "operator-1", authorized_at: "2026-09-22T00:00:00Z" },
      source_digest: "sha256:a",
    });

    render(<GateApprovalPanel projectName="demo" />);
    await waitFor(() => expect(screen.getAllByText("尚未作出决策")[0]).toBeInTheDocument());

    fireEvent.change(screen.getByPlaceholderText("源内容摘要"), { target: { value: "sha256:a" } });
    fireEvent.click(screen.getAllByText("批准")[0]);

    await waitFor(() => {
      expect(greenlightSpy).toHaveBeenCalledWith("demo", { source_digest: "sha256:a", action: "GREENLIGHT" });
    });
    await waitFor(() => {
      expect(screen.getByText("已记录 1 条决策")).toBeInTheDocument();
    });
    expect(useAppStore.getState().toast?.text).toBe("项目已获批准立项。");
  });

  it("surfaces a failure as a toast without crashing", async () => {
    vi.spyOn(API, "getGateHistory").mockResolvedValueOnce({ greenlight: [], publish_approval: [] });
    vi.spyOn(API, "greenlightProject").mockRejectedValueOnce(new Error("boom"));

    render(<GateApprovalPanel projectName="demo" />);
    await waitFor(() => expect(screen.getAllByText("尚未作出决策")[0]).toBeInTheDocument());

    fireEvent.change(screen.getByPlaceholderText("源内容摘要"), { target: { value: "sha256:a" } });
    fireEvent.click(screen.getAllByText("批准")[0]);

    await waitFor(() => {
      expect(useAppStore.getState().toast?.text).toContain("Gate 操作失败");
    });
  });
});
