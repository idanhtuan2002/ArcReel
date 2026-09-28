import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { GateApprovalPanel } from "./GateApprovalPanel";
import { useAppStore } from "@/stores/app-store";

describe("GateApprovalPanel", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.restoreAllMocks();
    vi.spyOn(API, "requestDeliverableToken").mockResolvedValue({
      download_token: "tok",
      expires_in: 300,
      deliverables: [],
    });
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

    fireEvent.change(screen.getAllByPlaceholderText("源内容摘要")[0], { target: { value: "sha256:a" } });
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

    fireEvent.change(screen.getAllByPlaceholderText("源内容摘要")[0], { target: { value: "sha256:a" } });
    fireEvent.click(screen.getAllByText("批准")[0]);

    await waitFor(() => {
      expect(useAppStore.getState().toast?.text).toContain("Gate 操作失败");
    });
  });

  it("lists approved finals, downloads one with a fresh token and fills the Gate D digest", async () => {
    const digest = "sha256:" + "a".repeat(64);
    vi.spyOn(API, "getGateHistory").mockResolvedValue({ greenlight: [], publish_approval: [] });
    const tokenSpy = vi
      .spyOn(API, "requestDeliverableToken")
      .mockResolvedValueOnce({
        download_token: "tok-list",
        expires_in: 300,
        deliverables: [{ episode: 1, target_ref: "FINAL", sha256: digest }],
      })
      .mockResolvedValueOnce({
        download_token: "tok-download",
        expires_in: 300,
        deliverables: [{ episode: 1, target_ref: "FINAL", sha256: digest }],
      });
    const clicks: string[] = [];
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(this.href);
    });

    render(<GateApprovalPanel projectName="demo" />);
    await waitFor(() => expect(screen.getByText("第 1 集 · FINAL")).toBeInTheDocument());

    fireEvent.click(screen.getByText("下载"));
    await waitFor(() => expect(clicks).toHaveLength(1));
    expect(clicks[0]).toContain("/projects/demo/export/deliverable?download_token=tok-download");
    expect(clicks[0]).toContain(`digest=${encodeURIComponent(digest)}`);
    expect(tokenSpy).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByText("用于发布审批"));
    expect(screen.getByPlaceholderText("交付物摘要")).toHaveValue(digest);
    clickSpy.mockRestore();
  });

  it("shows the empty state when no final is approved", async () => {
    vi.spyOn(API, "getGateHistory").mockResolvedValue({ greenlight: [], publish_approval: [] });

    render(<GateApprovalPanel projectName="demo" />);

    await waitFor(() => {
      expect(screen.getByText("暂无已批准且有效的成片；Final Cut 通过 gate API 批准。")).toBeInTheDocument();
    });
  });

  it("locks a factual script with its exact source and script digests", async () => {
    vi.spyOn(API, "getGateHistory").mockResolvedValue({ greenlight: [], publish_approval: [], script_lock: [] });
    const lockSpy = vi.spyOn(API, "scriptLock").mockResolvedValueOnce({
      decision_id: "d-2",
      action: "LOCK",
      sequence: 1,
      created_at: "2026-09-28T00:00:00Z",
      authorization: { authenticated_principal: "operator-1", authorized_at: "2026-09-28T00:00:00Z" },
      source_digest: "sha256:s",
      script_digest: "sha256:c",
    });

    render(<GateApprovalPanel projectName="demo" />);
    await waitFor(() => expect(screen.getAllByText("尚未作出决策")[0]).toBeInTheDocument());

    fireEvent.change(screen.getAllByPlaceholderText("源内容摘要")[1], { target: { value: "sha256:s" } });
    fireEvent.change(screen.getByPlaceholderText("脚本摘要"), { target: { value: "sha256:c" } });
    fireEvent.click(screen.getByText("锁定脚本"));

    await waitFor(() => {
      expect(lockSpy).toHaveBeenCalledWith("demo", {
        source_digest: "sha256:s",
        script_digest: "sha256:c",
        action: "LOCK",
      });
    });
    await waitFor(() => expect(useAppStore.getState().toast?.text).toBe("脚本已锁定。"));
  });
});
