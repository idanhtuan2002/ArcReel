import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ShotTargetState } from "../api/shotWorkflowClient";
import ShotWorkflowPage, { nextStep } from "./ShotWorkflowPage";

const BASE: ShotTargetState = {
  target_ref: { target_type: "SHOT", target_id: "scene-1-TAKE-1", registry_version: 1, version_digest: "sha256:t" },
  purpose: "Mia enters the lobby",
  target_duration: 5,
  location_ref: "location:lobby",
  binding: {
    status: "none",
    binding_id: null,
    binding_version: null,
    snapshot_digest: null,
    target_registry_version: null,
    has_spatial_set: false,
  },
  pair: { status: "none", binding_version: null, views: [] },
  shot: null,
  master_version: null,
};
const BOUND = { ...BASE.binding, status: "current" as const, binding_id: "m8b:x", binding_version: 1, snapshot_digest: "sha256:snap", target_registry_version: 1 };
const APPROVED = { status: "approved" as const, binding_version: 1, views: [] };
const HEAD = { candidate_id: "shot:scene-1-TAKE-1:b1", current_revision: 1, head_version: 1 };

const PNG = { MASTER: new Uint8Array([1, 2, 3]), REVERSE: new Uint8Array([4, 5, 6]) };
const DIGEST = {
  MASTER: "sha256:039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81",
  REVERSE: "sha256:787c798e39a5bc1910355bae6d0cd87a36b2e10fd0202a83e3bb6b005da83472",
};
const SNAPSHOT = {
  session_id: "s1",
  scene_ref: { target_type: "SCENE", target_id: "scene-1", registry_version: 1, version_digest: "sha256:s" },
  target_ref: BASE.target_ref,
  binding_id: "m8b:x",
  binding_version: 1,
  envelope_digest: "sha256:e",
  core_digest: "sha256:c",
  frames: [
    { role: "MASTER", receipt_id: "a", receipt_digest: "da", png_digest: DIGEST.MASTER },
    { role: "REVERSE", receipt_id: "z", receipt_digest: "dz", png_digest: DIGEST.REVERSE },
  ],
  expires_at: "2026-10-14T00:10:00Z",
};

function target(overrides: Partial<ShotTargetState>): ShotTargetState {
  return { ...BASE, ...overrides };
}

describe("nextStep", () => {
  it("follows the server state through the six steps", () => {
    expect(nextStep(BASE, null)).toBe("bind");
    expect(nextStep(target({ binding: { ...BOUND, status: "stale" } }), null)).toBe("bind");
    expect(nextStep(target({ binding: BOUND }), null)).toBe("review");
    expect(nextStep(target({ binding: { ...BOUND, binding_version: 2 }, pair: APPROVED }), null)).toBe("review");
    expect(nextStep(target({ binding: BOUND, pair: APPROVED }), null)).toBe("analyze");
    expect(nextStep(target({ binding: BOUND, pair: APPROVED }), HEAD)).toBe("promote");
    const promoted = { ...BOUND, binding_version: 2, has_spatial_set: true };
    expect(nextStep(target({ binding: promoted }), null)).toBe("generate");
    expect(nextStep(target({ binding: promoted, shot: { task_id: "t", status: "running" } }), null)).toBe("generate");
    expect(nextStep(target({ binding: promoted, shot: { task_id: "t", status: "failed" } }), null)).toBe("generate");
    expect(nextStep(target({ binding: promoted, shot: { task_id: "t", status: "succeeded" } }), null)).toBe("approve");
    expect(nextStep(target({ binding: promoted, master_version: 1 }), null)).toBe("done");
  });
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let state: ShotTargetState;
let approveResponse: () => Response;
const requests: { url: string; body: unknown }[] = [];

beforeEach(() => {
  requests.length = 0;
  approveResponse = () => json({ receipt: {} });
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    requests.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url.endsWith("/m8/spatial/targets")) return Promise.resolve(json([state]));
    if (url.includes("/r2/shots/")) {
      return Promise.resolve(json({ task_id: "task-1", target_registry_version: 1, binding_snapshot_digest: "sha256:snap", host_request_digest: "sha256:h" }));
    }
    if (url.includes("/gates/r2-shots/")) return Promise.resolve(approveResponse());
    if (url.endsWith("/review-sessions")) return Promise.resolve(json(SNAPSHOT));
    if (url.includes("/frames/")) {
      const role = url.endsWith("MASTER") ? "MASTER" : "REVERSE";
      return Promise.resolve(
        new Response(PNG[role], {
          status: 200,
          headers: { "X-Review-Attempt-Id": `att-${role}`, "X-Review-Png-Digest": DIGEST[role] },
        }),
      );
    }
    if (url.includes("/acknowledgments")) return Promise.resolve(json({}));
    if (url.endsWith("/candidates/shot%3Ascene-1-TAKE-1%3Ab1")) return Promise.resolve(json(HEAD));
    if (url.includes("/revisions/1")) {
      return Promise.resolve(
        json({
          candidate_id: HEAD.candidate_id,
          revision: 1,
          payload: {
            kind: "SPATIAL",
            spatial: {
              assertions: [
                { assertion_id: "a1", evidence_class: "VISIBLE", source_refs: ["master"], relation: "red cabinet on front wall", subject_refs: [], confidence: null, warnings: [] },
              ],
            },
          },
        }),
      );
    }
    if (url.endsWith("/promotion-previews")) return Promise.resolve(json({ detail: "m8_promotion_binding_stale" }, 409));
    return Promise.resolve(json({}, 404));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Shot workflow page", () => {
  it("generates against the target's current snapshot through the enqueue action", async () => {
    state = target({ binding: { ...BOUND, binding_version: 2, has_spatial_set: true } });
    render(<ShotWorkflowPage projectName="demo" episode={1} />);

    fireEvent.click(await screen.findByRole("button", { name: "生成镜头" }));

    await waitFor(() => expect(requests.some((request) => request.url.includes("/r2/shots/"))).toBe(true));
    const generate = requests.find((request) => request.url.includes("/r2/shots/"));
    expect(generate?.url).toBe("/api/v1/projects/demo/r2/shots/scene-1-TAKE-1/generate");
    expect(generate?.body).toMatchObject({
      expected_target_registry_version: 1,
      expected_binding_snapshot_digest: "sha256:snap",
      execution_profile_ref: "r2-wan27-r2v-two-view@1",
    });
  });

  it("shows the server's refusal when Gate C does not approve", async () => {
    state = target({
      binding: { ...BOUND, binding_version: 2, has_spatial_set: true },
      shot: { task_id: "task-1", status: "succeeded" },
    });
    approveResponse = () => json({ detail: "r2_shot_output_changed" }, 409);
    render(<ShotWorkflowPage projectName="demo" episode={1} />);

    fireEvent.change(await screen.findByRole("textbox", { name: "审批记录" }), { target: { value: "APR-1" } });
    fireEvent.click(screen.getByRole("button", { name: "审批为母版" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("r2_shot_output_changed");
    const approve = requests.find((request) => request.url.includes("/gates/r2-shots/"));
    expect(approve?.body).toEqual({ task_id: "task-1", approval_record: "APR-1" });
  });

  it("explains that pair review needs activated grants", async () => {
    state = target({ binding: BOUND, pair: { status: "unavailable", binding_version: null, views: [] } });
    render(<ShotWorkflowPage projectName="demo" episode={1} />);

    expect(await screen.findByText(/showrunner 授权/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "开始审阅" })).not.toBeInTheDocument();
  });
});

describe("Shot workflow review", () => {
  it("acknowledges a frame only when the reviewer confirms viewing it", async () => {
    vi.stubGlobal("createImageBitmap", vi.fn(() => Promise.resolve({})));
    vi.stubGlobal("URL", { ...URL, createObjectURL: () => "blob:frame", revokeObjectURL: () => undefined });
    state = target({ binding: BOUND });
    render(<ShotWorkflowPage projectName="demo" episode={1} />);

    fireEvent.click(await screen.findByRole("button", { name: "开始审阅" }));
    const confirmMaster = await screen.findByRole("button", { name: "我已查看 MASTER" });

    expect(requests.some((request) => request.url.includes("/acknowledgments"))).toBe(false);
    fireEvent.click(confirmMaster);
    await waitFor(() => expect(requests.filter((request) => request.url.includes("/acknowledgments"))).toHaveLength(1));
    expect(requests.find((request) => request.url.includes("/acknowledgments"))?.body).toEqual({
      attempt_id: "att-MASTER",
      role: "MASTER",
      png_digest: DIGEST.MASTER,
      decoded: true,
    });
    expect(screen.getByRole("button", { name: "批准画面对" })).toBeDisabled();
    vi.unstubAllGlobals();
  });
});

describe("Shot workflow promotion", () => {
  it("asks for a fresh preview on each attempt, so an expired one never blocks a retry", async () => {
    state = target({ binding: BOUND, pair: APPROVED });
    render(<ShotWorkflowPage projectName="demo" episode={1} />);

    const keep = await screen.findByRole("button", { name: "保留 1 条约束" });
    fireEvent.click(keep);
    await screen.findByRole("alert");
    fireEvent.click(keep);
    await waitFor(() => expect(requests.filter((request) => request.url.endsWith("/promotion-previews"))).toHaveLength(2));

    const ids = requests
      .filter((request) => request.url.endsWith("/promotion-previews"))
      .map((request) => (request.body as { command_id: string }).command_id);
    expect(new Set(ids).size).toBe(2);
  });
});
