import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

import type { Finding, RunSummary, StoryRun } from "../api/storyClient";
import StoryAuthoringPage from "./StoryAuthoringPage";

const PROVIDERS = {
  routes: [
    {
      provider_id: "custom-7",
      model_id: "qwen3.5-vimax:9b",
      label: "Ollama local · qwen3.5-vimax:9b",
      enabled: true,
      reason: null,
      cloud: false,
    },
    {
      provider_id: "custom-7",
      model_id: "gemma3:12b",
      label: "Ollama local · gemma3:12b",
      enabled: true,
      reason: null,
      cloud: false,
    },
  ],
};

const SELECTION = {
  provider_id: "custom-7",
  model_id: "qwen3.5-vimax:9b",
  endpoint: "ollama-chat",
  base_url: "http://localhost:11434",
  has_credential: false,
  digest: "sha256:s",
};
const BRIEF = {
  idea: "Minh về làng bán nhà.",
  genre: "đời thường",
  selection: SELECTION,
  judge_selection: null,
  story_target_syllables: 9000,
};

const EXCEPTION: Finding = {
  id: "F002",
  code: "CONTINUITY:location",
  severity: "NARRATIVE_CRITICAL",
  node_id: "scene_draft[1,1]",
  message: "chuyển cảnh đột ngột",
  quote: "Minh đứng ngoài vườn.",
};

function run(overrides: Partial<StoryRun> = {}): StoryRun {
  return {
    run_id: "story-1",
    phase: "READY_FOR_APPROVAL",
    block_reason: null,
    blocked_findings: [],
    brief: BRIEF,
    brief_digest: "sha256:brief",
    usage: {
      count_calls: 10,
      generate_calls: 10,
      input_tokens: 80000,
      output_tokens: 9000,
      model_milliseconds: 600000,
    },
    limits: { input_tokens_max: 1, output_tokens_max: 1, wall_clock_max_seconds: 1 },
    intents: {},
    offered: {
      manifest_digest: "sha256:manifest",
      export_digest: "sha256:export",
      scenes: [
        { node_id: "scene_draft[1,1]", chapter: 1, scene: 1, text: "Minh về làng.\n\nMinh đứng ngoài vườn." },
        { node_id: "scene_draft[2,1]", chapter: 2, scene: 1, text: "Lan mở cuốn sổ." },
      ],
      findings: [
        {
          id: "F001",
          code: "NO_DIALOGUE",
          severity: "STYLISTIC",
          node_id: "scene_draft[2,1]",
          message: "thiếu thoại",
          quote: "",
        },
        EXCEPTION,
      ],
      packaging: {
        titles: [
          { title: "Cuốn sổ", kind: "k" },
          { title: "Căn nhà", kind: "k" },
        ],
        blurbs: ["Minh về làng."],
        selling_points: [{ point: "Một bí mật", evidence_quote: "Lan mở cuốn sổ." }],
        tags: ["gia đình"],
      },
      exceptions_offered: ["F002"],
      completed_steps: [],
      blocked_step: null,
    },
    handoff: null,
    ...overrides,
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let runs: RunSummary[] = [];
let current: StoryRun = run();
let routes: Record<string, () => Response> = {};
let providers: () => Response = () => json(PROVIDERS);
const requests: { url: string; method: string; body: Record<string, unknown> | null }[] = [];

function posted(suffix: string): Record<string, unknown>[] {
  return requests.filter((item) => item.method === "POST" && item.url.endsWith(suffix)).map((item) => item.body ?? {});
}

function summary(phase: StoryRun["phase"] = current.phase): RunSummary {
  return { run_id: "story-1", phase, idea: BRIEF.idea, genre: BRIEF.genre, started_at: "2026-10-19T10:00:00Z" };
}

// The assertions read the English copy; the suite's shared setup runs in Chinese.
beforeAll(async () => {
  await i18n.changeLanguage("en");
});

afterAll(async () => {
  await i18n.changeLanguage("zh");
});

beforeEach(() => {
  runs = [summary()];
  current = run();
  routes = {};
  providers = () => json(PROVIDERS);
  requests.length = 0;
  sessionStorage.clear();
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    requests.push({
      url,
      method,
      body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null,
    });
    const route = method === "POST" ? Object.keys(routes).find((suffix) => url.endsWith(suffix)) : undefined;
    if (route) return Promise.resolve(routes[route]());
    if (url.endsWith("/story-routes")) return Promise.resolve(providers());
    if (url.endsWith("/story-runs") && method === "GET") return Promise.resolve(json({ runs }));
    if (url.endsWith("/story-runs/story-1") && method === "GET") return Promise.resolve(json(current));
    return Promise.resolve(json({}));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("a new story", () => {
  beforeEach(() => {
    runs = [];
  });

  it("offers only models on the story endpoint and keeps typed text across a reload until the run starts", async () => {
    const first = render(<StoryAuthoringPage projectName="demo" />);
    const writer = await screen.findByLabelText("Writing model");
    expect(
      within(writer)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Ollama local · qwen3.5-vimax:9b", "Ollama local · gemma3:12b"]);
    fireEvent.change(screen.getByLabelText("Idea"), { target: { value: "Minh về làng bán nhà." } });
    fireEvent.change(screen.getByLabelText("Genre"), { target: { value: "đời thường" } });
    first.unmount();

    render(<StoryAuthoringPage projectName="demo" />);
    expect(await screen.findByLabelText("Idea")).toHaveValue("Minh về làng bán nhà.");
    expect(screen.getByLabelText("Genre")).toHaveValue("đời thường");
  });

  it("selects a configured cloud writer and freezes its USD cap in the approval brief", async () => {
    providers = () =>
      json({
        routes: [
          ...PROVIDERS.routes,
          {
            provider_id: "gemini-aistudio",
            model_id: "gemini-2.5-flash",
            label: "Gemini · Gemini 2.5 Flash",
            enabled: true,
            reason: null,
            cloud: true,
          },
          {
            provider_id: "gemini-aistudio",
            model_id: "gemini-3.8-flash",
            label: "Gemini · Gemini 3.8 Flash",
            enabled: false,
            reason: "MISSING_CREDENTIAL",
            cloud: true,
          },
        ],
      });
    routes["/story-runs/brief"] = () =>
      json({
        brief: {
          ...BRIEF,
          selection: { ...SELECTION, provider_id: "gemini-aistudio", model_id: "gemini-2.5-flash" },
          limits: { currency: "USD", max_cost_minor_units: 250 },
        },
        brief_digest: "sha256:cloud",
      });
    render(<StoryAuthoringPage projectName="demo" />);
    const writer = await screen.findByLabelText("Writing model");
    expect(within(writer).getByRole("option", { name: /Gemini 3.8 Flash/ })).toBeDisabled();
    fireEvent.change(writer, { target: { value: "gemini-aistudio/gemini-2.5-flash" } });
    fireEvent.change(screen.getByLabelText("Cloud budget limit (USD)"), { target: { value: "2.50" } });
    fireEvent.change(screen.getByLabelText("Idea"), { target: { value: "A village story" } });
    fireEvent.change(screen.getByLabelText("Genre"), { target: { value: "drama" } });
    fireEvent.click(screen.getByRole("button", { name: "Prepare brief" }));
    expect(await screen.findByText("$2.50")).toBeInTheDocument();
    expect(posted("/story-runs/brief")[0]).toMatchObject({
      provider_id: "gemini-aistudio",
      model_id: "gemini-2.5-flash",
      max_cost_minor_units: 250,
    });
  });

  it("asks for a story model when none is configured", async () => {
    providers = () => json({ routes: [] });
    render(<StoryAuthoringPage projectName="demo" />);
    expect(await screen.findByText(/No story model is available/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Prepare brief" })).toBeDisabled();
  });

  it("shows the reason when the model list cannot be reached", async () => {
    providers = () => {
      throw new TypeError("Failed to fetch");
    };
    render(<StoryAuthoringPage projectName="demo" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Failed to fetch");
  });

  it("shows a refused brief in the Human's language", async () => {
    routes["/story-runs/brief"] = () =>
      json({ detail: { code: "ROUTE_NOT_QUALIFIED", detail: "story authoring needs the ollama-chat endpoint" } }, 422);
    render(<StoryAuthoringPage projectName="demo" />);
    fireEvent.change(await screen.findByLabelText("Idea"), { target: { value: "Minh về làng." } });
    fireEvent.change(screen.getByLabelText("Genre"), { target: { value: "đời thường" } });
    fireEvent.click(screen.getByRole("button", { name: "Prepare brief" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This model's endpoint cannot write stories");
  });

  it("starts the run only after the Human approves the exact brief, then clears the draft", async () => {
    routes["/story-runs/brief"] = () => json({ project_name: "demo", brief: BRIEF, brief_digest: "sha256:brief" });
    routes["/gates/greenlight"] = () => json({ decision_id: "gate-a-1", action: "GREENLIGHT", sequence: 1 });
    routes["/story-runs"] = () => {
      runs = [summary("RUNNING")];
      current = run({ phase: "RUNNING", offered: null });
      return json({ run_id: "story-1", brief_digest: "sha256:brief" });
    };
    render(<StoryAuthoringPage projectName="demo" />);
    fireEvent.change(await screen.findByLabelText("Idea"), { target: { value: "Minh về làng bán nhà." } });
    fireEvent.change(screen.getByLabelText("Genre"), { target: { value: "đời thường" } });
    fireEvent.change(screen.getByLabelText("Review model"), { target: { value: "custom-7/gemma3:12b" } });
    fireEvent.click(screen.getByRole("button", { name: "Prepare brief" }));

    expect(await screen.findByText("Approve this brief to start writing")).toBeInTheDocument();
    expect(posted("/story-runs/brief")[0]).toMatchObject({
      idea: "Minh về làng bán nhà.",
      provider_id: "custom-7",
      model_id: "qwen3.5-vimax:9b",
      judge_provider_id: "custom-7",
      judge_model_id: "gemma3:12b",
      story_target_syllables: 9000,
    });
    expect(posted("/story-runs")).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "Approve and start" }));
    expect(await screen.findByText(/The model is planning, writing and reviewing/)).toBeInTheDocument();
    expect(posted("/gates/greenlight")).toEqual([{ source_digest: "sha256:brief", action: "GREENLIGHT" }]);
    expect(posted("/story-runs")).toEqual([{ brief: BRIEF, gate_a_decision_id: "gate-a-1" }]);
    expect(sessionStorage.getItem("story-draft:demo")).toBeNull();
  });
});

describe("touchpoint 2", () => {
  it("shows each scene with its notes in the margin and the packaging", async () => {
    render(<StoryAuthoringPage projectName="demo" />);
    const margin = await screen.findByLabelText("Notes on scene 1.1");
    expect(within(margin).getByText("chuyển cảnh đột ngột")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Notes on scene 2.1")).getByText("thiếu thoại")).toBeInTheDocument();
    expect(screen.getByText("Lan mở cuốn sổ.")).toBeInTheDocument();
    expect(screen.getByText("Cuốn sổ")).toBeInTheDocument();
  });

  it("holds Approve until every exception is ticked and approves the manifest the Human read", async () => {
    routes["/approve"] = () => {
      current = run({ phase: "COMMITTED" });
      return json(current);
    };
    render(<StoryAuthoringPage projectName="demo" />);
    const approve = await screen.findByRole("button", { name: "Approve story" });
    expect(approve).toBeDisabled();
    const [inMargin, inDecision] = screen.getAllByRole("checkbox");
    expect(inMargin.closest("label")).toHaveTextContent("Keep as is");
    expect(inDecision.closest("label")).toHaveTextContent("Needs your decision · scene 1.1");
    expect(screen.getByText("0 of 1 decisions reviewed")).toBeInTheDocument();

    fireEvent.click(inMargin);
    expect(inDecision).toBeChecked();
    expect(screen.getByText("1 of 1 decisions reviewed")).toBeInTheDocument();
    expect(approve).toBeEnabled();
    fireEvent.click(approve);

    expect(await screen.findByRole("button", { name: "Send to video" })).toBeInTheDocument();
    expect(posted("/approve")).toEqual([{ manifest_digest: "sha256:manifest", accepted_exceptions: ["F002"] }]);
  });

  it("refuses an approval of a manuscript another tab already changed and reloads the current one", async () => {
    routes["/approve"] = () => json({ detail: { code: "STALE_MANIFEST", detail: "manifest changed" } }, 409);
    render(<StoryAuthoringPage projectName="demo" />);
    fireEvent.click((await screen.findAllByRole("checkbox"))[0]);
    fireEvent.click(screen.getByRole("button", { name: "Approve story" }));

    expect(await screen.findByText(/The manuscript changed since you opened it/)).toBeInTheDocument();
    const loads = requests.filter((item) => item.url.endsWith("/story-runs/story-1")).length;
    fireEvent.click(screen.getByRole("button", { name: "Load the current manuscript" }));
    await waitFor(() =>
      expect(requests.filter((item) => item.url.endsWith("/story-runs/story-1")).length).toBe(loads + 1),
    );
  });

  it("sends a revision request for the chosen part with the Human's note", async () => {
    routes["/revise"] = () => {
      current = run({ phase: "RUNNING", offered: null });
      return json(current);
    };
    render(<StoryAuthoringPage projectName="demo" />);
    fireEvent.change(await screen.findByLabelText("Part to revise"), { target: { value: "scene_draft[2,1]" } });
    fireEvent.change(screen.getByLabelText("What should change"), { target: { value: "Thêm thoại giữa Lan và mẹ." } });
    fireEvent.click(screen.getByRole("button", { name: "Send revision request" }));

    expect(await screen.findByText(/The model is planning, writing and reviewing/)).toBeInTheDocument();
    expect(posted("/revise")).toEqual([{ target: "scene_draft[2,1]", note: "Thêm thoại giữa Lan và mẹ." }]);
  });

  it("discards only on a second click", async () => {
    routes["/discard"] = () => {
      current = run({ phase: "DISCARDED", offered: null });
      return json(current);
    };
    render(<StoryAuthoringPage projectName="demo" />);
    fireEvent.click(await screen.findByRole("button", { name: "Discard" }));
    expect(posted("/discard")).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Click again to discard" }));
    expect(await screen.findByText(/Nothing from this run was kept/)).toBeInTheDocument();
    expect(posted("/discard")).toHaveLength(1);
  });
});

describe("other phases", () => {
  it("shows why a run stopped and retries it", async () => {
    current = run({
      phase: "BLOCKED_QUALITY",
      offered: null,
      block_reason: "manuscript_review: the last chapter does not resolve the central conflict",
      blocked_findings: [{ ...EXCEPTION, code: "NO_ENDING", severity: "HARD_STRUCTURAL", quote: "" }],
    });
    routes["/retry"] = () => {
      current = run({ phase: "RUNNING", offered: null });
      return json(current);
    };
    render(<StoryAuthoringPage projectName="demo" />);
    expect(await screen.findByText(/does not resolve the central conflict/)).toBeInTheDocument();
    const loads = () =>
      requests.filter((item) => item.method === "GET" && item.url.endsWith("/story-runs/story-1")).length;
    const before = loads();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText(/The model is planning, writing and reviewing/)).toBeInTheDocument();
    // The run is working again, so the page reads it again and keeps polling.
    await waitFor(() => expect(loads()).toBeGreaterThan(before));
  });

  it("finishes a pending hand-off with its own command and offers a new name on a name clash", async () => {
    current = run({
      phase: "COMMITTED",
      handoff: {
        command_id: "cmd-pending",
        filename: "cuon-so",
        export_digest: "sha256:export",
        done: false,
        path: null,
      },
    });
    routes["/send-to-video"] = () => json({ detail: { code: "UPLOAD_FAILED", detail: "source exists" } }, 409);
    render(<StoryAuthoringPage projectName="demo" />);
    fireEvent.click(await screen.findByRole("button", { name: "Send to video" }));

    expect(await screen.findByRole("button", { name: "Send under a new name" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send under a new name" }));
    await waitFor(() => expect(posted("/send-to-video")).toHaveLength(2));
    expect(posted("/send-to-video")).toEqual([
      { command_id: "cmd-pending", on_conflict: "fail" },
      { command_id: "cmd-pending", on_conflict: "rename" },
    ]);
  });

  it("withdraws an approved story only on a second click and says running video jobs continue", async () => {
    current = run({
      phase: "COMMITTED",
      handoff: {
        command_id: "cmd-1",
        filename: "cuon-so",
        export_digest: "sha256:export",
        done: true,
        path: "source/cuon-so.txt",
      },
    });
    render(<StoryAuthoringPage projectName="demo" />);
    expect(await screen.findByText("Sent to video as source/cuon-so.txt.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send to video" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));
    expect(screen.getByText(/Video jobs already started keep running/)).toBeInTheDocument();
    expect(posted("/withdraw")).toEqual([]);
  });
});
