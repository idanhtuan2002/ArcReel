import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PackagingPage from "./PackagingPage";

const FINDING = { finding_id: "f-1", rule_id: "title-length", severity: "BLOCKING", subject_locator: "title" };
const GROUPS = [
  {
    group_id: "titles",
    field: "title",
    variants: [
      { variant_id: "t1", value: { text: "A history of the river" }, asset_role: null },
      { variant_id: "t2", value: { text: "The river that made a valley" }, asset_role: null },
    ],
  },
];
const CHAPTERS = [
  { start_ms: 0, title: "Source" },
  { start_ms: 60000, title: "Delta" },
];
const ARCHIVE = `sha256:${"a".repeat(64)}`;
const SELECTION = {
  selection_id: "sel-1",
  selection_digest: "sha256:sel",
  head_version: 1,
  preview: { preview_id: "pv-1", expected_head_version: 0, expires_at: "2026-10-29T10:00:00Z", candidate_revision: 1, selected_variant_ids: ["t2"], waivers: [] },
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

interface Slot {
  head_version: number;
  exportable: boolean;
  refusal_code: string | null;
  readiness: { state: string; reasons: string[]; disposition_decision: string | null } | null;
  selection: typeof SELECTION | null;
  exports: {
    archive_digest: string;
    archive_byte_size: number;
    download_token: string | null;
    exported_at: string;
    selection_id: string;
    current: boolean;
  }[];
}

const EMPTY: Slot = { head_version: 0, exportable: false, refusal_code: "M10_STALE_HEAD", readiness: null, selection: null, exports: [] };
const READY = { state: "READY", reasons: [], disposition_decision: "ACCEPT" };

let routes: Record<string, (body: Record<string, unknown>) => Response | Promise<Response>> = {};
/** The slot the server reports for product surface "youtube-long"; every other surface is empty. */
let slot: Slot;
/** When set, slot reads wait for it before answering. */
let slotGate: Promise<void> | null;
const requests: { url: string; method: string; body: Record<string, unknown> }[] = [];

function posted(suffix: string): Record<string, unknown>[] {
  return requests.filter((item) => item.method === "POST" && item.url.endsWith(suffix)).map((item) => item.body);
}

beforeEach(() => {
  requests.length = 0;
  slot = EMPTY;
  slotGate = null;
  routes = {
    "/packaging/revisions": (body) =>
      json({
        revision: {
          candidate_id: "pkg-1",
          revision: 1,
          payload_digest: "sha256:pay",
          payload: { variant_groups: (body.draft as { variant_groups: unknown[] }).variant_groups },
        },
        head: { head_version: 1 },
      }),
    "/packaging/checks": () => json({ observation_id: "obs-1", status: "FAIL", findings: [FINDING] }),
    "/packaging/previews": (body) =>
      json({
        preview: { ...SELECTION.preview, waivers: body.waivers, selected_variant_ids: body.selected_variant_ids },
        preview_digest: "sha256:pv",
      }),
    "/packaging/selections": () => {
      slot = { head_version: 1, exportable: true, refusal_code: null, readiness: READY, selection: SELECTION, exports: [] };
      return json(SELECTION);
    },
    "/packaging/exports": () => {
      slot = {
        ...slot,
        exports: [
          {
            archive_digest: ARCHIVE,
            archive_byte_size: 10,
            download_token: "tok",
            exported_at: "2026-10-29T09:00:00Z",
            selection_id: "sel-1",
            current: true,
          },
        ],
      };
      return json({
        status: "EXPORTED",
        archive_digest: ARCHIVE,
        archive_byte_size: 10,
        download_token: "tok",
        manifest: { entries: [{ path: "video/output.mp4", byte_size: 5, content_digest: "sha256:v" }] },
      });
    },
  };
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    requests.push({ url, method, body });
    if (method === "GET" && url.includes("/packaging/slot?")) {
      const surface = new URL(url, "http://test").searchParams.get("product_surface");
      const answer = () => json(surface === "youtube-long" ? slot : EMPTY);
      return slotGate ? slotGate.then(answer) : Promise.resolve(answer());
    }
    const route = Object.keys(routes).find((suffix) => url.endsWith(suffix));
    return Promise.resolve(route ? routes[route](body) : json({}, 404));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function fill(label: RegExp, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

const SAVE = /Save package|Save as new revision|Lưu gói|保存包/;
const CHECK = /Run check|Chạy kiểm tra|运行检查/;
const PREVIEW = /Preview selection|Xem trước|预览选定/;
const SELECT = /Select as showrunner|Chọn với vai trò|以 showrunner/;
const EXPORT = /Export archive|Xuất tệp|导出归档/;
const WAIVER = /Waiver reason|Lý do miễn trừ|豁免理由/;

async function walkToSelection(): Promise<void> {
  fill(/Quality run ID|Mã lượt|质量评估运行 ID/, "run-1");
  fill(/Quality run digest|Digest của lượt|质量评估运行摘要/, "sha256:run");
  fill(/^Title$|^Tiêu đề$|^标题$/, "A history of the river");
  fill(/^Chapters|^Chương|^章节/, JSON.stringify(CHAPTERS));
  fill(/^Alternative groups|^Nhóm phương án|^备选组/, JSON.stringify(GROUPS));
  fill(/^Age restriction|^Giới hạn độ tuổi|^年龄限制/, "13+");
  fireEvent.click(screen.getByLabelText(/^Paid promotion$|^Quảng cáo trả phí$|^付费推广$/));
  fill(/Video artifact key|Khóa artifact|视频工件键/, "masters/ep-1");
  fill(/^Cohort$|^Nhóm$|^群组$/, "cohort-a");
  fill(/Product surface|Bề mặt sản phẩm|产品界面/, "youtube-long");
  fireEvent.click(screen.getByRole("button", { name: SAVE }));
  await screen.findByText(/Revision 1 saved|Đã lưu bản sửa đổi 1|已保存修订 1/);
  fireEvent.click(screen.getByRole("button", { name: CHECK }));
  await screen.findByText(/failed one or more blocking rules|không đạt|未通过/);
  fill(WAIVER, "brand title");
  fireEvent.click(screen.getByRole("radio", { name: "t2" }));
  fireEvent.click(screen.getByRole("button", { name: PREVIEW }));
  await screen.findByText(/Preview ready|Bản xem trước|预览有效/);
  fireEvent.click(screen.getByRole("button", { name: SELECT }));
  await screen.findByText(/Current selection: revision 1, version 1|Lựa chọn hiện tại|当前选定/);
}

describe("Packaging page", () => {
  it("authors every package field, then walks to a download the server lists for the slot", async () => {
    const { container } = render(<PackagingPage projectName="demo" />);
    await walkToSelection();
    fireEvent.click(screen.getByRole("button", { name: EXPORT }));
    const link = await screen.findByRole("link", { name: /Download archive|Tải tệp|下载归档/ });
    expect(link).toHaveAttribute("href", `/api/v1/projects/demo/packaging/exports/${"a".repeat(64)}/archive?token=tok`);

    const draft = posted("/packaging/revisions")[0].draft as Record<string, unknown>;
    expect(draft).not.toHaveProperty("provenance");
    expect(draft).toMatchObject({
      chapters: CHAPTERS,
      variant_groups: GROUPS,
      audience_classification: { audience_category: "general", age_restriction: "13+" },
      disclosure: { synthetic_media: true, paid_promotion: true },
    });
    expect(posted("/packaging/previews")[0]).toMatchObject({
      source_artifact_key: "masters/ep-1",
      cohort_id: "cohort-a",
      product_surface: "youtube-long",
      selected_variant_ids: ["t2"],
      waivers: [{ rule_id: "title-length", finding_id: "f-1", reason: "brand title" }],
    });
    expect(posted("/packaging/exports")[0]).toMatchObject({ selection_id: "sel-1", selection_digest: "sha256:sel" });
    const commands = requests.filter((item) => item.method === "POST").map((item) => item.body.command_id);
    expect(new Set(commands).size).toBe(commands.length);
    expect(container.querySelectorAll('[aria-current="step"]')).toHaveLength(0);

    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((violation) => violation.id)).toEqual([]);
  });

  it("keeps later steps disabled until the earlier step has a server result", () => {
    const { container } = render(<PackagingPage projectName="demo" />);
    expect(screen.getByRole("button", { name: CHECK })).toBeDisabled();
    expect(screen.getByRole("button", { name: PREVIEW })).toBeDisabled();
    expect(screen.getByRole("button", { name: SELECT })).toBeDisabled();
    expect(screen.getByRole("button", { name: EXPORT })).toBeDisabled();
    expect(container.querySelectorAll('[aria-current="step"]')).toHaveLength(1);
  });

  it("makes an earlier preview unselectable as soon as a waiver, choice or slot changes", async () => {
    render(<PackagingPage projectName="demo" />);
    fill(/Quality run ID|Mã lượt|质量评估运行 ID/, "run-1");
    fill(/Quality run digest|Digest của lượt|质量评估运行摘要/, "sha256:run");
    fill(/^Title$|^Tiêu đề$|^标题$/, "A history of the river");
    fill(/^Alternative groups|^Nhóm phương án|^备选组/, JSON.stringify(GROUPS));
    fireEvent.click(screen.getByRole("button", { name: SAVE }));
    await screen.findByText(/Revision 1 saved|Đã lưu bản sửa đổi 1|已保存修订 1/);
    fireEvent.click(screen.getByRole("button", { name: CHECK }));
    await screen.findByText(/failed one or more blocking rules|không đạt|未通过/);
    fill(WAIVER, "brand title");
    fireEvent.click(screen.getByRole("radio", { name: "t2" }));
    fireEvent.click(screen.getByRole("button", { name: PREVIEW }));
    await screen.findByText(/Preview ready|Bản xem trước|预览有效/);
    expect(screen.getByRole("button", { name: SELECT })).toBeEnabled();

    fill(WAIVER, "a different reason");
    expect(screen.getByRole("button", { name: SELECT })).toBeDisabled();
    expect(screen.queryByText(/Preview ready|Bản xem trước|预览有效/)).not.toBeInTheDocument();
    fill(WAIVER, "brand title");
    fireEvent.click(screen.getByRole("radio", { name: "t1" }));
    expect(screen.getByRole("button", { name: SELECT })).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "t2" }));
    fill(/Product surface|Bề mặt sản phẩm|产品界面/, "shorts");
    expect(screen.getByRole("button", { name: SELECT })).toBeDisabled();
    expect(posted("/packaging/selections")).toHaveLength(0);
  });

  it("locks check and preview while the draft has unsaved edits", async () => {
    render(<PackagingPage projectName="demo" />);
    fill(/Quality run ID|Mã lượt|质量评估运行 ID/, "run-1");
    fill(/Quality run digest|Digest của lượt|质量评估运行摘要/, "sha256:run");
    fill(/^Title$|^Tiêu đề$|^标题$/, "A history of the river");
    fireEvent.click(screen.getByRole("button", { name: SAVE }));
    await screen.findByText(/Revision 1 saved|Đã lưu bản sửa đổi 1|已保存修订 1/);
    expect(screen.getByRole("button", { name: CHECK })).toBeEnabled();
    fill(/^Title$|^Tiêu đề$|^标题$/, "Another title");
    expect(screen.getByText(/unsaved changes|chưa lưu|未保存/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: CHECK })).toBeDisabled();
  });

  it("refuses a draft whose JSON field is not a list without calling the server", () => {
    render(<PackagingPage projectName="demo" />);
    fill(/Quality run ID|Mã lượt|质量评估运行 ID/, "run-1");
    fill(/^Title$|^Tiêu đề$|^标题$/, "A history of the river");
    fill(/^Chapters|^Chương|^章节/, "{not json");
    fireEvent.click(screen.getByRole("button", { name: SAVE }));
    expect(screen.getByRole("alert")).toHaveTextContent(/not valid JSON|không phải JSON|不是有效的 JSON/);
    expect(posted("/packaging/revisions")).toHaveLength(0);
  });

  it("shows the server's refusal and withholds export when the slot's selection is no longer exportable", async () => {
    slot = {
      head_version: 2,
      exportable: false,
      refusal_code: "M10_DISPOSITION_STALE",
      readiness: { state: "NOT_READY", reasons: ["DISPOSITION_NOT_ACCEPTED"], disposition_decision: "REWORK" },
      selection: SELECTION,
      exports: [
        {
          archive_digest: ARCHIVE,
          archive_byte_size: 10,
          download_token: null,
          exported_at: "2026-10-29T09:00:00Z",
          selection_id: "sel-1",
          current: true,
        },
        {
          archive_digest: `sha256:${"b".repeat(64)}`,
          archive_byte_size: 10,
          download_token: null,
          exported_at: "2026-10-28T09:00:00Z",
          selection_id: "sel-0",
          current: false,
        },
      ],
    };
    render(<PackagingPage projectName="demo" />);
    fill(/Video artifact key|Khóa artifact|视频工件键/, "masters/ep-1");
    fill(/^Cohort$|^Nhóm$|^群组$/, "cohort-a");
    fill(/Product surface|Bề mặt sản phẩm|产品界面/, "youtube-long");
    expect(await screen.findByText(/M10_DISPOSITION_STALE/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: EXPORT })).toBeDisabled();
    expect(screen.queryByRole("link", { name: /Download archive|Tải tệp|下载归档/ })).not.toBeInTheDocument();
    expect(screen.getAllByText(/only while this selection is current|vẫn là lựa chọn hiện tại|仍为当前选定/).length).toBe(2);
    expect(screen.getByText(/From a replaced selection|Thuộc lựa chọn đã bị thay|来自已被取代的选定/)).toBeInTheDocument();
    expect(screen.getByText(/NOT_READY/)).toHaveTextContent(/REWORK/);
  });

  it("shows the server's refusal and rereads the slot when a selection became stale", async () => {
    routes["/packaging/selections"] = () => json({ detail: "The package selection changed; reload and try again" }, 409);
    render(<PackagingPage projectName="demo" />);
    await walkToSelection().catch(() => undefined);
    expect(await screen.findByRole("alert")).toHaveTextContent(/selection changed/);
    const selectedAt = requests.findIndex((item) => item.method === "POST" && item.url.endsWith("/packaging/selections"));
    expect(selectedAt).toBeGreaterThan(-1);
    await waitFor(() =>
      expect(
        requests.slice(selectedAt + 1).some((item) => item.method === "GET" && item.url.includes("/packaging/slot?")),
      ).toBe(true),
    );
    expect(screen.getByText(/No package is selected|Chưa có gói nào|尚未选定/)).toBeInTheDocument();
  });

  it("reads the slot being edited when an action started for another slot finishes", async () => {
    let finishSelection: (response: Response) => void = () => undefined;
    routes["/packaging/selections"] = () =>
      new Promise<Response>((resolve) => {
        finishSelection = (response) => {
          slot = { head_version: 1, exportable: true, refusal_code: null, readiness: READY, selection: SELECTION, exports: [] };
          resolve(response);
        };
      });
    render(<PackagingPage projectName="demo" />);
    await walkToSelection().catch(() => undefined);
    fill(/Product surface|Bề mặt sản phẩm|产品界面/, "shorts");
    finishSelection(json(SELECTION));
    expect(await screen.findByText(/No package is selected|Chưa có gói nào|尚未选定/)).toBeInTheDocument();
    expect(screen.queryByText(/Loading the slot|Đang tải vị trí|正在加载槽位/)).not.toBeInTheDocument();
    const surfaces = requests
      .filter((item) => item.method === "GET" && item.url.includes("/packaging/slot?"))
      .map((item) => new URL(item.url, "http://test").searchParams.get("product_surface"));
    expect(surfaces.at(-1)).toBe("shorts");
  });

  it("shows nothing as exportable while a slot it returns to is being reread", async () => {
    slot = {
      head_version: 1,
      exportable: true,
      refusal_code: null,
      readiness: READY,
      selection: SELECTION,
      exports: [],
    };
    render(<PackagingPage projectName="demo" />);
    fill(/Video artifact key|Khóa artifact|视频工件键/, "masters/ep-1");
    fill(/^Cohort$|^Nhóm$|^群组$/, "cohort-a");
    fill(/Product surface|Bề mặt sản phẩm|产品界面/, "youtube-long");
    await waitFor(() => expect(screen.getByRole("button", { name: EXPORT })).toBeEnabled());
    fill(/Product surface|Bề mặt sản phẩm|产品界面/, "shorts");
    await screen.findByText(/No package is selected|Chưa có gói nào|尚未选定/);
    let release: () => void = () => undefined;
    slotGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    fill(/Product surface|Bề mặt sản phẩm|产品界面/, "youtube-long");
    expect(screen.getByRole("button", { name: EXPORT })).toBeDisabled();
    expect(screen.getByText(/Loading the slot|Đang tải vị trí|正在加载槽位/)).toBeInTheDocument();
    release();
    await waitFor(() => expect(screen.getByRole("button", { name: EXPORT })).toBeEnabled());
  });

  it("has no detectable accessibility violations when empty", async () => {
    const { container } = render(<PackagingPage projectName="demo" />);
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument());
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((violation) => violation.id)).toEqual([]);
  });
});
