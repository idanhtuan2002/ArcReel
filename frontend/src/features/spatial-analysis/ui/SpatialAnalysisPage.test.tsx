import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useProjectsStore } from "@/stores/projects-store";
import type { ProjectData } from "@/types";

import SpatialAnalysisPage from "./SpatialAnalysisPage";

const SOURCES = [
  { artifact_key: "key-1", shot_id: "SH01", master_version: 1 },
  { artifact_key: "key-2", shot_id: "SH02", master_version: 1 },
];
const HEAD = { candidate_id: "spatial-ep1-x", current_revision: 1, head_version: 1 };
const ASSERTIONS = [
  { assertion_id: "a1", evidence_class: "VISIBLE", source_refs: ["master"], relation: "red cabinet on front wall", subject_refs: [], confidence: null, warnings: [] },
  { assertion_id: "a2", evidence_class: "INFERRED", source_refs: ["master"], relation: "hidden corridor may continue", subject_refs: [], confidence: 0.4, warnings: [] },
  { assertion_id: "a3", evidence_class: "GAP", source_refs: ["reverse"], relation: "left rear corner unseen", subject_refs: [], confidence: null, warnings: [] },
];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let executeResponse: () => Response;
const requests: { url: string; body: unknown }[] = [];

beforeEach(() => {
  requests.length = 0;
  useProjectsStore.setState({
    currentProjectName: "demo",
    currentProjectData: { title: "Demo", episodes: [{ episode: 1, title: "The Hook" }] } as unknown as ProjectData,
  });
  executeResponse = () => json(HEAD);
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    requests.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url.includes("/spatial/sources")) return Promise.resolve(json(SOURCES));
    if (url.includes("/spatial/frames")) {
      const key = (JSON.parse(String(init?.body)) as { parent_artifact_key: string }).parent_artifact_key;
      return Promise.resolve(json({ receipt_id: `r-${key}`, receipt_digest: `d-${key}` }));
    }
    if (url.includes("/spatial/executions")) return Promise.resolve(executeResponse());
    if (url.includes("/revisions/1")) {
      return Promise.resolve(json({ candidate_id: HEAD.candidate_id, revision: 1, payload: { kind: "SPATIAL", spatial: { assertions: ASSERTIONS } } }));
    }
    return Promise.resolve(json({}));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function fillScene(name = "Lobby") {
  render(<SpatialAnalysisPage projectName="demo" episode={1} />);
  const scene = await screen.findByRole("textbox");
  fireEvent.change(scene, { target: { value: name } });
}

describe("Spatial analysis page", () => {
  it("analyzes two shots and groups the findings by evidence class", async () => {
    await fillScene("  Lobby  ");
    expect(screen.getByText("EPISODE 01 · SPATIAL")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /分析空间/ }));

    expect(await screen.findByText("red cabinet on front wall")).toBeInTheDocument();
    expect(screen.getByText("hidden corridor may continue")).toBeInTheDocument();
    expect(screen.getByText("MASTER · 40%")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "未覆盖" })).toHaveTextContent("left rear corner unseen");
    const execution = requests.find((request) => request.url.includes("/spatial/executions"));
    expect(execution?.body).toMatchObject({
      episode: 1,
      scene_name: "Lobby",
      master: { receipt_id: "r-key-1", receipt_digest: "d-key-1" },
      reverse: { receipt_id: "r-key-2", receipt_digest: "d-key-2" },
    });
  });

  it("refuses the same shot for both views before any request", async () => {
    await fillScene();
    const [, reverse] = screen.getAllByRole("combobox");
    fireEvent.change(reverse, { target: { value: "key-1" } });

    expect(screen.getByText("请为两个视角选择不同的镜头。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /分析空间/ })).toBeDisabled();
  });

  it("shows the server's reason and retries with the same command", async () => {
    executeResponse = () => json({ detail: "空间分析暂不可用" }, 503);
    await fillScene();

    fireEvent.click(screen.getByRole("button", { name: /分析空间/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("空间分析暂不可用");

    executeResponse = () => json(HEAD);
    fireEvent.click(screen.getByRole("button", { name: /分析空间/ }));
    await screen.findByText("red cabinet on front wall");
    const commands = requests
      .filter((request) => request.url.includes("/spatial/executions"))
      .map((request) => (request.body as { command_id: string }).command_id);
    expect(commands).toHaveLength(2);
    expect(commands[0]).toBe(commands[1]);
  });

  it("asks for two approved shots when the episode has fewer", async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => Promise.resolve(json([SOURCES[0]])));
    render(<SpatialAnalysisPage projectName="demo" episode={1} />);

    expect(await screen.findByText(/至少需要两个已审批的视频镜头/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: /分析空间/ })).not.toBeInTheDocument());
  });
});
