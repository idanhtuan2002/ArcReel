import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useProjectsStore } from "@/stores/projects-store";
import type { ProjectData } from "@/types";

import { writeConflictSnapshot } from "../recovery/draftRecovery";
import { keepAside, resetKeptAsideMemory } from "../recovery/keptAside";
import { useCanvasStore } from "../state/canvasStore";
import { useSaveStatusStore } from "../state/saveStatusStore";
import CreativeCanvasPage from "./CreativeCanvasPage";

const CONTEXT = {
  lineage: {
    project_name: "demo",
    content_basis_digest: `sha256:${"1".repeat(64)}`,
    approved_master_id: null,
    approved_master_digest: null,
    creative_profile_id: "arcreel.host",
    creative_profile_version: "1",
    policy_digest: `sha256:${"2".repeat(64)}`,
  },
  created_by: "default",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let contextResponse: () => Response;

beforeEach(() => {
  window.localStorage.clear();
  resetKeptAsideMemory();
  useCanvasStore.getState().reset();
  useSaveStatusStore.getState().reset();
  useProjectsStore.setState({
    currentProjectName: "demo",
    currentProjectData: { title: "Demo", episodes: [{ episode: 1, title: "The Hook", script_file: "scripts/episode_1.json" }] } as unknown as ProjectData,
    currentScripts: {},
  });
  contextResponse = () => json(CONTEXT);
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.includes("/m8/exploration/context")) return Promise.resolve(contextResponse());
    if (url.includes("/m8/exploration/candidates/")) return Promise.resolve(json({ detail: "not found" }, 404));
    return Promise.resolve(json({}));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function renderReady() {
  render(<CreativeCanvasPage projectName="demo" episode={1} />);
  await waitFor(() => expect(useCanvasStore.getState().phase).toBe("ready"));
}

describe("Creative Canvas page", () => {
  it("opens an empty Canvas under the episode title with an invitation to start", async () => {
    await renderReady();

    expect(screen.getByRole("heading", { level: 1, name: "The Hook" })).toBeInTheDocument();
    expect(screen.getByText("EPISODE 01 · CANVAS")).toBeInTheDocument();
    expect(screen.getByText("添加节拍或导入本集镜头即可开始。")).toBeInTheDocument();
    expect(screen.getByRole("toolbar", { name: "画布工具" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent(/暂无更改/);
  });

  it("shows why the Canvas could not load and retries", async () => {
    contextResponse = () => json({ detail: "本集没有剧本。" }, 404);
    render(<CreativeCanvasPage projectName="demo" episode={1} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/本集没有剧本。/);

    contextResponse = () => json(CONTEXT);
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(useCanvasStore.getState().phase).toBe("ready"));
  });

  it("adds a beat from the toolbar and undoes it from the keyboard", async () => {
    await renderReady();
    const undo = screen.getByRole("button", { name: "撤销" });
    expect(undo).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "添加节拍" }));

    expect(useCanvasStore.getState().graph.nodes.map((node) => node.type)).toEqual(["beat"]);
    expect(undo).toBeEnabled();

    fireEvent.keyDown(window, { key: "z", ctrlKey: true });
    expect(useCanvasStore.getState().graph.nodes).toEqual([]);
  });

  it("disables grouping until two or more nodes are selected", async () => {
    await renderReady();

    expect(screen.getByRole("button", { name: "编组" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "生成分镜板" })).toBeDisabled();
  });

  it("says when the episode has no shots to import", async () => {
    await renderReady();

    fireEvent.click(screen.getByRole("button", { name: "导入镜头" }));

    expect(screen.getByText("本集还没有已生成的图片或视频。")).toBeInTheDocument();
  });

  it("offers both choices for work kept aside and clears the conflict on a choice", async () => {
    writeConflictSnapshot(
      { userId: "default", projectName: "demo", candidateId: "canvas-episode-1" },
      { nodes: [], edges: [], viewport: null, metadata: null, timestamp: new Date(0).toISOString() },
    );
    await renderReady();

    expect(screen.getByRole("alert")).toHaveTextContent(/此画布已在其他标签页或设备上更改。/);
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "添加节拍" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "舍弃我的版本" }));
    expect(useCanvasStore.getState().conflict).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "确认舍弃" }));

    await waitFor(() => expect(useCanvasStore.getState().conflict).toBeNull());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });;

  it("asks again before discarding the next kept-aside version", async () => {
    const scope = { userId: "default", projectName: "demo", candidateId: "canvas-episode-1" };
    writeConflictSnapshot(scope, { nodes: [], edges: [], viewport: null, metadata: null, timestamp: new Date(0).toISOString() });
    keepAside(scope, { nodes: [], edges: [], viewport: null, metadata: { second: true }, timestamp: new Date(1).toISOString() });
    await renderReady();

    fireEvent.click(screen.getByRole("button", { name: "舍弃我的版本" }));
    fireEvent.click(screen.getByRole("button", { name: "确认舍弃" }));
    await waitFor(() => expect(useCanvasStore.getState().conflict?.metadata).toEqual({ second: true }));

    fireEvent.click(screen.getByRole("button", { name: "舍弃我的版本" }));

    expect(useCanvasStore.getState().conflict?.metadata).toEqual({ second: true });
  });
});

