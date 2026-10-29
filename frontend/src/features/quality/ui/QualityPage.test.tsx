import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores/auth-store";

import QualityPage from "./QualityPage";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const MASTER = { artifact_key: "key-final", selected_candidate_id: "CAND-1", approval_record: "APR-1", resolvable: true };
const PROFILE = { profile_id: "prof-1", revision: 2, cohort_id: "cohort", product_surface: "video", profile_digest: "sha256:p", policy: {} };
const OBS = (id: string, requirement: string, status = "PASS", findings: unknown[] = []) => ({
  observation_id: id,
  observation_type: requirement === "review" ? "NARRATIVE" : "TECHNICAL",
  requirement_id: requirement,
  slot_id: requirement === "review" ? "human" : requirement.replace("technical-", ""),
  status,
  observed_at: "2026-10-29T10:00:00Z",
  findings,
});
const FINDING = { finding_id: "f-1", rule_id: "review", severity: "BLOCKING", subject_locator: "visible-defects@whole" };
const RUN = (readiness: string, id = "01a1run000000000") => ({
  run: { run_id: id, profile_id: "prof-1", profile_revision: 2, subject_digest: "sha256:s" },
  run_digest: "sha256:r",
  cohort_id: "run-cohort",
  product_surface: "run-surface",
  disposition_version: 1,
  current_disposition_id: "d-1",
  validity: { state: "CURRENT", reasons: [] },
  readiness: { state: readiness, reasons: [] },
});
const SEALED_PROFILE = {
  action: "publish_profile",
  request: {
    command: { command_id: "publish-x" },
    subject: { profile_draft: { profile_id: "prof-new", revision: 1, cohort_id: "cohort", product_surface: "video", supersession_effect: "HISTORICAL_ONLY", policy_digest: "sha256:pol" } },
  },
  seal: "seal-abc",
};

let gets: Record<string, () => Response> = {};
let posts: Record<string, (body: Record<string, unknown>) => Response> = {};
const sent: { path: string; body: Record<string, unknown> }[] = [];

beforeEach(() => {
  sent.length = 0;
  window.localStorage.clear();
  useAuthStore.setState({ username: "showrunner" });
  gets = {
    "/quality/masters": () => json({ masters: [MASTER] }),
    "/quality/profiles": () => json({ profiles: [PROFILE] }),
    "/quality/profiles/prof-1/revisions": () => json({ revisions: [{ revision: 1, profile_digest: "a" }, { revision: 2, profile_digest: "b" }] }),
    "/quality/profiles/prof-1/revisions/2": () => json({ profile: PROFILE }),
    "/quality/profiles/prof-1/revisions/1": () => json({ profile: { ...PROFILE, revision: 1 } }),
    "/quality/template": () => json({ policy: { schema_id: "m10.quality-policy.v2" } }),
    "/quality/observations": () =>
      json({
        subject_digest: "sha256:s",
        observations: [
          OBS("o-c", "technical-container"),
          OBS("o-d", "technical-decode"),
          OBS("o-r1", "review", "FAIL", [FINDING]),
          OBS("o-r2", "review", "PASS"),
        ],
      }),
    "/quality/probes": () => json({ probes: [] }),
    "/quality/runs": () => json({ runs: [RUN("READY")] }),
  };
  posts = {
    "/quality/profiles/prepare": () => json(SEALED_PROFILE),
    "/quality/profiles": () => json({ profile: PROFILE }),
    "/quality/runs/prepare": (body) => json({ action: "seal_run", request: { command: { command_id: body.command_id }, subject: { observations: [] } }, seal: "s" }),
    "/quality/dispositions/prepare": (body) =>
      json({ action: "dispose", request: { command: { command_id: body.command_id }, subject: { quality_run_id: body.run_id, decision: body.decision } }, seal: "s" }),
  };
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const path = new URL(String(input), "http://test").pathname.replace(/^\/api\/v1\/projects\/demo/, "");
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    if (init?.method === "POST") {
      sent.push({ path, body });
      return Promise.resolve(posts[path]?.(body) ?? json({}, 404));
    }
    return Promise.resolve(gets[path]?.() ?? json({}, 404));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function choose(): Promise<void> {
  render(<QualityPage projectName="demo" />);
  fireEvent.change(await screen.findByLabelText(/Approved video|Video đã duyệt|已批准的视频/), { target: { value: "key-final" } });
  fireEvent.change(screen.getByLabelText(/^Quality profile$|^Profile chất lượng$|^质量配置$/), { target: { value: "prof-1" } });
  await screen.findByLabelText(/^Revision$|^修订$/);
}

async function preparePublication(): Promise<void> {
  render(<QualityPage projectName="demo" />);
  fireEvent.click(await screen.findByRole("button", { name: /Load template|Nạp mẫu|加载模板/ }));
  await screen.findByLabelText(/Quality policy|Chính sách chất lượng|质量策略/);
  fireEvent.click(screen.getByRole("button", { name: /^Prepare publication$|^Chuẩn bị publish$|^准备发布$/ }));
}

describe("Quality page", () => {
  it("keeps the probes locked until a video and a profile revision are chosen", async () => {
    render(<QualityPage projectName="demo" />);
    await screen.findByLabelText(/Approved video|Video đã duyệt|已批准的视频/);
    expect(screen.getByRole("button", { name: /Check container|Kiểm tra container|检查容器/ })).toBeDisabled();
  });

  it("shows every consequential field of the prepared publication and submits it exactly", async () => {
    await preparePublication();
    const group = await screen.findByRole("group", { name: /Confirm the prepared request|Xác nhận|确认/ });
    expect(within(group).getByText("prof-new r1")).toBeInTheDocument();
    expect(within(group).getByText("cohort · video")).toBeInTheDocument();
    expect(within(group).getByText("HISTORICAL_ONLY")).toBeInTheDocument();
    expect(within(group).getByText("sha256:pol")).toBeInTheDocument();
    expect(screen.getByLabelText(/Quality policy|Chính sách chất lượng|质量策略/)).toBeDisabled();
    fireEvent.click(within(group).getByRole("button", { name: /^Publish profile$|^发布配置$/ }));
    await waitFor(() => expect(sent.some((item) => item.path === "/quality/profiles")).toBe(true));
    expect(sent.find((item) => item.path === "/quality/profiles")?.body).toEqual({ request: SEALED_PROFILE.request, seal: SEALED_PROFILE.seal });
    await waitFor(() => expect(window.localStorage.length).toBe(0));
  });

  it("keeps a failed submission per actor and command and offers it again after a reload", async () => {
    posts["/quality/profiles"] = () => json({ detail: "busy" }, 503);
    await preparePublication();
    fireEvent.click(await screen.findByRole("button", { name: /^Publish profile$|^发布配置$/ }));
    await screen.findByRole("alert");
    expect(window.localStorage.getItem("arcreel.m10c.pending:demo:showrunner:profiles:publish-x")).not.toBeNull();
    useAuthStore.setState({ username: "someone-else" });
    const { unmount } = render(<QualityPage projectName="demo" />);
    await screen.findAllByLabelText(/Approved video|Video đã duyệt|已批准的视频/);
    expect(screen.queryByRole("button", { name: /^Resend$|^Gửi lại$|^重新发送$/ })).not.toBeInTheDocument();
    unmount();
  });

  it("seals the observation the operator chose for each requirement", async () => {
    await choose();
    fireEvent.click(await screen.findByLabelText(/^PASS · /, { selector: 'input[name="qa-seal-technical-container"]' }));
    fireEvent.click(screen.getByLabelText(/^PASS · /, { selector: 'input[name="qa-seal-technical-decode"]' }));
    const reviewOptions = screen.getAllByRole("radio").filter((radio) => radio.getAttribute("name") === "qa-seal-review");
    fireEvent.click(reviewOptions[1]);
    fireEvent.click(screen.getByRole("button", { name: /Prepare run|Chuẩn bị run|准备运行/ }));
    await waitFor(() => expect(sent.some((item) => item.path === "/quality/runs/prepare")).toBe(true));
    expect(sent.find((item) => item.path === "/quality/runs/prepare")?.body.observation_ids).toEqual(["o-c", "o-d", "o-r2"]);
  });

  it("decides on the chosen run and binds the findings chosen for a waiver", async () => {
    await choose();
    fireEvent.click(await screen.findByRole("radio", { name: /01a1run0/ }));
    fireEvent.change(screen.getByLabelText(/^Decision$|^Quyết định$|^决定$/), { target: { value: "WAIVE" } });
    fireEvent.change(screen.getByLabelText(/^Reason$|^Lý do$|^理由$/), { target: { value: "brand style" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /visible-defects@whole/ }));
    fireEvent.click(screen.getByRole("button", { name: /Prepare decision|Chuẩn bị quyết định|准备决定/ }));
    await waitFor(() => expect(sent.some((item) => item.path === "/quality/dispositions/prepare")).toBe(true));
    expect(sent.find((item) => item.path === "/quality/dispositions/prepare")?.body).toMatchObject({
      run_id: "01a1run000000000",
      decision: "WAIVE",
      expected_disposition_version: 1,
      waiver_bindings: [{ rule_id: "review", finding_id: "f-1", scope: "review:human", justification: "brand style" }],
    });
  });

  it("hands a READY run to Packaging with that run's own cohort and surface", async () => {
    await choose();
    const link = await screen.findByRole("link", { name: /Package this run|Đóng gói run này|打包此运行/ });
    expect(link).toHaveAttribute("href", expect.stringContaining("cohort=run-cohort"));
    expect(link).toHaveAttribute("href", expect.stringContaining("surface=run-surface"));
  });

  it("does not offer packaging for a run that is not ready", async () => {
    gets["/quality/runs"] = () => json({ runs: [RUN("NOT_READY")] });
    await choose();
    expect(await screen.findByText(/Not ready for packaging|Chưa sẵn sàng|尚不能打包/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Package this run/ })).not.toBeInTheDocument();
  });

  it("can work on an older immutable revision", async () => {
    await choose();
    fireEvent.change(screen.getByLabelText(/^Revision$|^修订$/), { target: { value: "1" } });
    await waitFor(() => expect(screen.getByLabelText(/^Revision$|^修订$/)).toHaveValue("1"));
  });

  it("has no detectable accessibility violations", async () => {
    const { container } = render(<QualityPage projectName="demo" />);
    await screen.findByLabelText(/Approved video|Video đã duyệt|已批准的视频/);
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((violation) => violation.id)).toEqual([]);
  });
});
