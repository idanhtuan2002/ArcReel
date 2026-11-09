import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useConfigStatusStore } from "@/stores/config-status-store";
import { useProjectsStore } from "@/stores/projects-store";
import { ProjectsPage } from "@/components/pages/ProjectsPage";
import type { Phase } from "@/types";

vi.mock("@/components/pages/CreateProjectModal", () => ({
  CreateProjectModal: () => <div data-testid="create-project-modal">Create Project Modal</div>,
}));

function renderPage() {
  const location = memoryLocation({ path: "/app/projects", record: true });
  return {
    ...render(
      <Router hook={location.hook}>
        <ProjectsPage />
      </Router>,
    ),
    location,
  };
}

describe("ProjectsPage", () => {
  beforeEach(() => {
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
    useAppStore.setState(useAppStore.getInitialState(), true);
    useConfigStatusStore.setState(useConfigStatusStore.getInitialState(), true);
    vi.restoreAllMocks();
  });

  function summary(name: string, title: string, extra: Record<string, unknown> = {}) {
    return {
      name,
      title,
      style: "",
      thumbnail: null,
      updated_at: new Date().toISOString(),
      project_kind: "film" as "film" | "story",
      story_project: null,
      status: {
        phase: "production" as Phase,
        phase_progress: 0,
        needs_repair: false,
        repair_reason: null,
        assets: {
          character: { total: 0, available: 0, stale: 0 },
          scene: { total: 0, available: 0, stale: 0 },
          prop: { total: 0, available: 0, stale: 0 },
        },
        episodes_summary: { total: 4, scripted: 4, in_production: 1, completed: 2 },
      },
      ...extra,
    };
  }

  function mockIndex(items: ReturnType<typeof summary>[]) {
    const counts = {
      all: items.length,
      story: items.filter((i) => i.project_kind === "story").length,
      film: items.filter((i) => i.project_kind !== "story").length,
    };
    return vi.spyOn(API, "projectIndex").mockImplementation((query = {}) =>
      Promise.resolve({
        total: query.kind && query.kind !== "all" ? counts[query.kind] : items.length,
        counts,
        offset: 0,
        limit: 50,
        items: items.filter((i) => !query.kind || query.kind === "all" || (i.project_kind === "story") === (query.kind === "story")),
      } as never),
    );
  }

  const QUIET = {
    counts: { decision: 0, blocked: 0, running: 0, tasks: 0 },
    lanes: { decision: [], blocked: [], running: [] },
    tasks: [],
  };

  it("opens external agent access from the lobby top bar", async () => {
    vi.spyOn(API, "operations").mockResolvedValue(QUIET as never);
    mockIndex([]);
    renderPage();

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "外部智能体接入" }));

    expect(screen.getByRole("dialog", { name: "外部智能体接入" })).toBeInTheDocument();
  });

  it("lists projects in a paged table with kind tabs and opens a story project on its story", async () => {
    vi.spyOn(API, "operations").mockResolvedValue(QUIET as never);
    mockIndex([
      summary("ben-do", "Bến đò", { project_kind: "story", films: 2 }),
      summary("ben-do-phim", "Bến đò — phim", { story_project: "ben-do" }),
    ]);
    const { location } = renderPage();

    const table = await screen.findByRole("table");
    expect(within(table).getByRole("link", { name: "Bến đò" })).toHaveAttribute("href", "/app/projects/ben-do/story");
    expect(within(table).getByText("← ben-do")).toBeInTheDocument();
    expect(within(table).getAllByText("2/4")).toHaveLength(2);

    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: /故事/ }));
    await waitFor(() => expect(API.projectIndex).toHaveBeenLastCalledWith(expect.objectContaining({ kind: "story" }), expect.anything()));
    await user.click(await screen.findByText("Bến đò"));
    await waitFor(() => expect(location.history?.at(-1)).toBe("/app/projects/ben-do/story"));
  });

  it("shows what needs the operator across projects and folds the strip", async () => {
    vi.spyOn(API, "operations").mockResolvedValue({
      counts: { decision: 1, blocked: 1, running: 0, tasks: 3 },
      lanes: {
        decision: [{ lane: "decision", kind: "story_run", project: "a", title: "Truyện A", project_kind: "story", run_id: "r1", state: "READY_FOR_APPROVAL" }],
        blocked: [{ lane: "blocked", kind: "production_run", project: "b", title: "Phim B", project_kind: "film", run_id: "r2", state: "BLOCKED_BUDGET" }],
        running: [],
      },
      tasks: [{ project: "b", title: "Phim B", tasks: 3 }],
    } as never);
    mockIndex([]);
    renderPage();

    expect(await screen.findByRole("link", { name: /Truyện A/ })).toHaveAttribute("href", "/app/projects/a/story");
    expect(screen.getByRole("link", { name: /Phim B/ })).toHaveAttribute("href", "/app/projects/b");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "待你处理" }));
    expect(screen.queryByRole("link", { name: /Truyện A/ })).not.toBeInTheDocument();
    expect(screen.getByText("1 待决定")).toBeInTheDocument();
  });

  it("shows an empty library with a way to create the first project", async () => {
    vi.spyOn(API, "operations").mockResolvedValue(QUIET as never);
    mockIndex([]);
    renderPage();

    expect(await screen.findByText("还没有项目。")).toBeInTheDocument();
    expect(screen.getByText("目前没有需要你处理的事。")).toBeInTheDocument();
  });

  it("opens create project modal after clicking new project button", async () => {
    vi.spyOn(API, "operations").mockResolvedValue(QUIET as never);
    mockIndex([]);

    renderPage();
    await screen.findByText("还没有项目。");
    expect(screen.queryByTestId("create-project-modal")).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "创建项目" })[0]);

    await waitFor(() => {
      expect(screen.getByTestId("create-project-modal")).toBeInTheDocument();
    });
  });

  it("imports a zip project, refreshes the list, and navigates to the workspace", async () => {
    vi.spyOn(API, "operations").mockResolvedValue(QUIET as never);
    mockIndex([]);
    vi.spyOn(API, "importProject").mockResolvedValue({
      success: true,
      project_name: "imported-demo",
      project: {
        title: "Imported Demo",
        content_mode: "narration",
        style: "Anime",
        episodes: [],
        characters: {},
        scenes: {},
        props: {},
      },
      warnings: ["发现未识别的附加文件/目录: extras"],
      conflict_resolution: "none",
      diagnostics: {
        auto_fixed: [{ code: "missing_clues_field", message: "segments[0]: 补全缺失字段 clues_in_segment" }],
        warnings: [{ code: "validation_warning", message: "发现未识别的附加文件/目录: extras" }],
      },
    });

    const { container, location } = renderPage();
    await screen.findByText("还没有项目。");

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["zip"], "project.zip", { type: "application/zip" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(API.importProject).toHaveBeenCalledWith(file, "prompt");
    });
    // 当存在 warnings/auto_fixed 时先弹诊断对话框，关闭后才跳转
    expect(await screen.findByText("导入诊断")).toBeInTheDocument();
    expect(useAppStore.getState().toast?.text).toContain("自动修复");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => {
      expect(location.history?.at(-1)).toBe("/app/projects/imported-demo");
    });
  });

  it("shows a structured toast when import fails", async () => {
    vi.spyOn(API, "operations").mockResolvedValue(QUIET as never);
    mockIndex([]);
    const error = new Error("导入包校验失败") as Error & {
      detail?: string;
      errors?: string[];
      warnings?: string[];
      diagnostics?: {
        blocking: { code: string; message: string }[];
        auto_fixable: { code: string; message: string }[];
        warnings: { code: string; message: string }[];
      };
    };
    error.detail = "导入包校验失败";
    error.errors = ["缺少 project.json", "缺少 scripts/episode_1.json", "缺少角色图"];
    error.warnings = ["发现未识别的附加文件/目录: extras"];
    error.diagnostics = {
      blocking: [
        { code: "validation_error", message: "缺少 project.json" },
        { code: "validation_error", message: "缺少 scripts/episode_1.json" },
      ],
      auto_fixable: [
        { code: "missing_clues_field", message: "segments[0]: 补全缺失字段 clues_in_segment" },
      ],
      warnings: [
        { code: "validation_warning", message: "发现未识别的附加文件/目录: extras" },
      ],
    };
    vi.spyOn(API, "importProject").mockRejectedValue(error);

    const { container } = renderPage();
    await screen.findByText("还没有项目。");

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["zip"], "broken.zip", { type: "application/zip" })] },
    });

    await waitFor(() => {
      expect(screen.getByText("导入失败诊断")).toBeInTheDocument();
    });
    expect(screen.getByText("缺少 project.json")).toBeInTheDocument();
    expect(screen.getByText("缺少 scripts/episode_1.json")).toBeInTheDocument();
    expect(screen.getByText("segments[0]: 补全缺失字段 clues_in_segment")).toBeInTheDocument();
  });

  it("opens a secondary confirmation when import hits a duplicate project id", async () => {
    vi.spyOn(API, "operations").mockResolvedValue(QUIET as never);
    mockIndex([]);
    const conflictError = new Error("检测到项目编号冲突") as Error & {
      status?: number;
      detail?: string;
      errors?: string[];
      conflict_project_name?: string;
    };
    conflictError.status = 409;
    conflictError.detail = "检测到项目编号冲突";
    conflictError.errors = ["项目编号 'demo' 已存在"];
    conflictError.conflict_project_name = "demo";

    vi.spyOn(API, "importProject")
      .mockRejectedValueOnce(conflictError)
      .mockResolvedValueOnce({
        success: true,
        project_name: "demo-renamed",
        project: {
          title: "Renamed Demo",
          content_mode: "narration",
          style: "Anime",
          episodes: [],
          characters: {},
          scenes: {},
          props: {},
        },
        warnings: [],
        conflict_resolution: "renamed",
        diagnostics: {
          auto_fixed: [],
          warnings: [],
        },
      });

    const { container, location } = renderPage();
    await screen.findByText("还没有项目。");

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["zip"], "project.zip", { type: "application/zip" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    expect(await screen.findByText("检测到项目编号重复")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "自动重命名导入" }));

    await waitFor(() => {
      expect(API.importProject).toHaveBeenNthCalledWith(1, file, "prompt");
    });
    await waitFor(() => {
      expect(API.importProject).toHaveBeenNthCalledWith(2, file, "rename");
    });
    await waitFor(() => {
      expect(location.history?.at(-1)).toBe("/app/projects/demo-renamed");
    });
  });

  it("names the project and the backend's reason when deleting fails", async () => {
    vi.spyOn(API, "operations").mockResolvedValue(QUIET as never);
    mockIndex([summary("first", "First"), summary("second", "Second")]);
    vi.spyOn(API, "deleteProject").mockRejectedValue(new Error("项目名称 'second' 非法"));

    renderPage();
    const user = userEvent.setup();
    const row = (await screen.findByRole("link", { name: "Second" })).closest("tr") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "删除项目" }));
    const dialog = await screen.findByRole("dialog", { name: "删除项目" });
    await user.click(within(dialog).getByRole("button", { name: "删除项目" }));

    await waitFor(() => {
      expect(useAppStore.getState().toast?.text).toBe("删除项目「Second」失败：项目名称 'second' 非法");
    });
  });
});
