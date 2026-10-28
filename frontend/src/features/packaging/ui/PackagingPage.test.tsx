import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PackagingPage from "./PackagingPage";

const REVISION = {
  revision: {
    candidate_id: "pkg-1",
    revision: 1,
    payload_digest: "sha256:pay",
    payload: { variant_groups: [{ group_id: "titles", field: "title", variants: [{ variant_id: "t1" }, { variant_id: "t2" }] }] },
  },
  head: { head_version: 1 },
};
const FINDING = { finding_id: "f-1", rule_id: "title-length", severity: "BLOCKING", subject_locator: "title" };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let routes: Record<string, () => Response> = {};
const requests: { url: string; body: Record<string, unknown> }[] = [];

function posted(suffix: string): Record<string, unknown>[] {
  return requests.filter((item) => item.url.endsWith(suffix)).map((item) => item.body);
}

beforeEach(() => {
  requests.length = 0;
  routes = {
    "/packaging/revisions": () => json(REVISION),
    "/packaging/checks": () => json({ observation_id: "obs-1", status: "FAIL", findings: [FINDING] }),
    "/packaging/previews": () =>
      json({
        preview: { preview_id: "pv-1", expected_head_version: 0, expires_at: "2026-10-29T10:00:00Z", selected_variant_ids: ["t2"] },
        preview_digest: "sha256:pv",
      }),
    "/packaging/selections": () => json({ selection_id: "sel-1", selection_digest: "sha256:sel", head_version: 1 }),
    "/packaging/exports": () =>
      json({
        status: "EXPORTED",
        archive_digest: `sha256:${"a".repeat(64)}`,
        archive_byte_size: 10,
        download_token: "tok",
        manifest: { entries: [{ path: "video/output.mp4", byte_size: 5, content_digest: "sha256:v" }] },
      }),
  };
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    requests.push({ url, body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {} });
    const route = Object.keys(routes).find((suffix) => url.endsWith(suffix));
    return Promise.resolve(route ? routes[route]() : json({}, 404));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function fill(label: RegExp, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

async function walkToExport(): Promise<void> {
  fill(/Quality run ID|Mã lượt|质量评估运行 ID/, "run-1");
  fill(/Quality run digest|Digest của lượt|质量评估运行摘要/, "sha256:run");
  fill(/^Title$|^Tiêu đề$|^标题$/, "A history of the river");
  fireEvent.click(screen.getByRole("button", { name: /Save package|Lưu gói|保存包/ }));
  await screen.findByText(/Revision 1 saved|Đã lưu bản sửa đổi 1|已保存修订 1/);
  fireEvent.click(screen.getByRole("button", { name: /Run check|Chạy kiểm tra|运行检查/ }));
  await screen.findByText(/failed one or more blocking rules|không đạt|未通过/);
  fill(/Waiver reason|Lý do miễn trừ|豁免理由/, "brand title");
  fireEvent.click(screen.getByRole("radio", { name: "t2" }));
  fireEvent.click(screen.getByRole("button", { name: /Preview selection|Xem trước|预览选定/ }));
  await screen.findByText(/Preview ready|Bản xem trước|预览有效/);
  fireEvent.click(screen.getByRole("button", { name: /Select as showrunner|Chọn với vai trò|以 showrunner/ }));
  await screen.findByText(/Selected \(version 1\)|Đã chọn|已选定/);
}

describe("Packaging page", () => {
  it("walks one package from revision to a downloadable export, sending only server-bound commands", async () => {
    render(<PackagingPage projectName="demo" />);
    await walkToExport();
    fireEvent.click(screen.getByRole("button", { name: /Export archive|Xuất tệp|导出归档/ }));
    const link = await screen.findByRole("link", { name: /Download archive|Tải tệp|下载归档/ });
    expect(link).toHaveAttribute("href", `/api/v1/projects/demo/packaging/exports/${"a".repeat(64)}/archive?token=tok`);

    expect(posted("/packaging/revisions")[0]).not.toHaveProperty("draft.provenance");
    expect(posted("/packaging/previews")[0]).toMatchObject({
      selected_variant_ids: ["t2"],
      waivers: [{ rule_id: "title-length", finding_id: "f-1", reason: "brand title" }],
    });
    const commands = requests.map((item) => item.body.command_id);
    expect(new Set(commands).size).toBe(commands.length);
  });

  it("keeps later steps disabled until the earlier step has a server result", () => {
    render(<PackagingPage projectName="demo" />);
    expect(screen.getByRole("button", { name: /Run check|Chạy kiểm tra|运行检查/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Preview selection|Xem trước|预览选定/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Select as showrunner|Chọn với vai trò|以 showrunner/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Export archive|Xuất tệp|导出归档/ })).toBeDisabled();
  });

  it("shows the server's refusal when a selection became stale", async () => {
    routes["/packaging/selections"] = () => json({ detail: "The package selection changed; reload and try again" }, 409);
    render(<PackagingPage projectName="demo" />);
    await walkToExport().catch(() => undefined);
    expect(await screen.findByRole("alert")).toHaveTextContent(/selection changed/);
  });

  it("has no detectable accessibility violations", async () => {
    const { container } = render(<PackagingPage projectName="demo" />);
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument());
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((violation) => violation.id)).toEqual([]);
  });
});
