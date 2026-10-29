import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import QualityPage from "./QualityPage";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const MASTER = { artifact_key: "key-final", artifact_path: "final.mp4", selected_candidate_id: "CAND-1", resolvable: true };
const PROFILE = { profile_id: "prof-1", revision: 1, cohort_id: "cohort", product_surface: "video", profile_digest: "sha256:p", policy: {} };
const SEALED = { action: "profiles", request: { command: { command_id: "publish-x" }, subject: {} }, seal: "seal-abc" };
const RUN = (readiness: string) => ({
  run: { run_id: "01a1run000000000", profile_id: "prof-1", profile_revision: 1, subject_digest: "sha256:s" },
  run_digest: "sha256:r",
  disposition_version: 1,
  current_disposition_id: "d-1",
  validity: { state: "CURRENT", reasons: [] },
  readiness: { state: readiness, reasons: [] },
});

let routes: Record<string, (body: Record<string, unknown>) => Response> = {};
const posts: { url: string; body: Record<string, unknown> }[] = [];

beforeEach(() => {
  posts.length = 0;
  window.localStorage.clear();
  routes = {
    "/quality/masters": () => json({ masters: [MASTER] }),
    "/quality/profiles": () => json({ profiles: [PROFILE] }),
    "/quality/template": () => json({ policy: { schema_id: "m10.quality-policy.v2" } }),
    "/quality/observations": () => json({ subject_digest: "sha256:s", observations: [] }),
    "/quality/runs": () => json({ runs: [RUN("READY")] }),
    "/quality/profiles/prepare": () => json(SEALED),
  };
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    if (init?.method === "POST") posts.push({ url, body });
    const path = new URL(url, "http://test").pathname;
    const route = Object.keys(routes).find((suffix) => path.endsWith(suffix) && (init?.method === "POST") === suffix.endsWith("prepare") || (path.endsWith(suffix) && !suffix.endsWith("prepare") && init?.method !== "POST"));
    if (init?.method === "POST" && !route) return Promise.resolve(routes["/quality/profiles/submit"]?.(body) ?? json({ profile: PROFILE }));
    return Promise.resolve(route ? routes[route](body) : json({}, 404));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function choose(): Promise<void> {
  render(<QualityPage projectName="demo" />);
  const master = await screen.findByLabelText(/Approved video|Video đã duyệt|已批准的视频/);
  fireEvent.change(master, { target: { value: "key-final" } });
  fireEvent.change(screen.getByLabelText(/^Quality profile$|^Profile chất lượng$|^质量配置$/), { target: { value: "prof-1@1" } });
}

describe("Quality page", () => {
  it("keeps the probes locked until a video and a profile are chosen", async () => {
    render(<QualityPage projectName="demo" />);
    await screen.findByLabelText(/Approved video|Video đã duyệt|已批准的视频/);
    expect(screen.getByRole("button", { name: /Check container|Kiểm tra container|检查容器/ })).toBeDisabled();
  });

  it("shows the server-prepared request and submits it exactly as sealed", async () => {
    render(<QualityPage projectName="demo" />);
    fireEvent.click(await screen.findByRole("button", { name: /Load template|Nạp mẫu|加载模板/ }));
    await screen.findByLabelText(/Quality policy|Chính sách chất lượng|质量策略/);
    fireEvent.click(screen.getByRole("button", { name: /^Prepare publication$|^Chuẩn bị publish$|^准备发布$/ }));
    expect(await screen.findByText("publish-x")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Publish profile$|^Publish profile$|^发布配置$/ }));
    await waitFor(() => expect(posts.some((p) => p.url.endsWith("/quality/profiles"))).toBe(true));
    const submitted = posts.find((p) => p.url.endsWith("/quality/profiles"));
    expect(submitted?.body).toEqual({ request: SEALED.request, seal: SEALED.seal });
    await waitFor(() => expect(window.localStorage.getItem("arcreel.m10c.pending:demo:profiles")).toBeNull());
  });

  it("keeps a sealed request in browser storage when the submit fails, so it can be resent", async () => {
    routes["/quality/profiles/submit"] = () => json({ detail: "busy" }, 503);
    render(<QualityPage projectName="demo" />);
    fireEvent.click(await screen.findByRole("button", { name: /Load template|Nạp mẫu|加载模板/ }));
    await screen.findByLabelText(/Quality policy|Chính sách chất lượng|质量策略/);
    fireEvent.click(screen.getByRole("button", { name: /^Prepare publication$|^Chuẩn bị publish$|^准备发布$/ }));
    fireEvent.click(await screen.findByRole("button", { name: /^Publish profile$|^发布配置$/ }));
    await screen.findByRole("alert");
    expect(JSON.parse(window.localStorage.getItem("arcreel.m10c.pending:demo:profiles") ?? "null")).toEqual(SEALED);
  });

  it("offers packaging only for a run the server reports current and READY", async () => {
    await choose();
    const link = await screen.findByRole("link", { name: /Package this run|Đóng gói run này|打包此运行/ });
    expect(link).toHaveAttribute("href", expect.stringContaining("/app/projects/demo/packaging?run=01a1run000000000"));
    expect(link).toHaveAttribute("href", expect.stringContaining("artifact=key-final"));
  });

  it("does not offer packaging for a run that is not ready", async () => {
    routes["/quality/runs"] = () => json({ runs: [RUN("NOT_READY")] });
    await choose();
    expect(await screen.findByText(/Not ready for packaging|Chưa sẵn sàng|尚不能打包/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Package this run/ })).not.toBeInTheDocument();
  });

  it("has no detectable accessibility violations", async () => {
    const { container } = render(<QualityPage projectName="demo" />);
    await screen.findByLabelText(/Approved video|Video đã duyệt|已批准的视频/);
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((violation) => violation.id)).toEqual([]);
  });
});
