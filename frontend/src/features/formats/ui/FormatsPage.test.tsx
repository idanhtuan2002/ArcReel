import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NO_OVERLAY, STANDARD_PROFILES, boxFromPercent, boxValue, type PlanSummary, type TechnicalCheck } from "../api/formatClient";
import FormatsPage from "./FormatsPage";

const SOURCE = { artifact_key: "episode_video:1", label: "episode_video · 1", master_version: 2, content_digest: "sha256:m" };
const ITEMS = ["focal_subject", "action", "shot_intent", "on_screen_text", "captions", "timing", "audio"];
const CHECKS: TechnicalCheck[] = ["dimensions", "ratio", "video_codec", "fps", "duration", "audio", "decode", "overlay"].map((name) => ({
  name,
  observed: name === "overlay" ? [] : 1,
  expected: name === "overlay" ? [] : 1,
  verdict: "PASS",
}));

function summary(overrides: Partial<PlanSummary> = {}): PlanSummary {
  return {
    plan: {
      plan_id: "square-pad-1",
      source_master_id: "episode_video:1@v2",
      source_master_digest: "sha256:m",
      output_profile: STANDARD_PROFILES[2],
      overlay_constraints: NO_OVERLAY,
      reframe_decisions: [
        {
          decision_id: "square-pad-1:reframe",
          kind: "PAD",
          source_span: { x0: "0", y0: "0", x1: "1", y1: "1", width: 1920, height: 1080, subject: { x0: "2/5", y0: "1/4", x1: "3/5", y1: "3/4" } },
          target_span: { x0: "0", y0: "7/32", x1: "1", y1: "25/32", width: 1080, height: 1080 },
          rationale: "keep the whole frame",
          semantic_risk: "LOW",
        },
      ],
      plan_digest: "sha256:p",
    },
    renders: [{ execution_id: "exec-1", plan_id: "square-pad-1", artifact_digest: "sha256:a", replayed: false }],
    technical: { report_id: "tech-1", artifact_digest: "sha256:a", checks: CHECKS, passed: true },
    semantic: null,
    ...overrides,
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let sources = [SOURCE];
let plans: PlanSummary[] = [];
let routes: Record<string, () => Response> = {};
const requests: { url: string; method: string; body: unknown }[] = [];

function posted(suffix: string): Record<string, unknown>[] {
  return requests.filter((item) => item.method === "POST" && item.url.endsWith(suffix)).map((item) => item.body as Record<string, unknown>);
}

beforeEach(() => {
  sources = [SOURCE];
  plans = [summary()];
  routes = {};
  requests.length = 0;
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:clip") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    requests.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    // Routes answer the writes and the clip downloads; the page loads come from `sources` and `plans`.
    const route = method === "POST" || url.includes("/clips/") ? Object.keys(routes).find((suffix) => url.endsWith(suffix)) : undefined;
    if (route) return Promise.resolve(routes[route]());
    if (url.endsWith("/m8/formats/sources")) return Promise.resolve(json(sources));
    if (url.endsWith("/m8/formats/plans") && method === "GET") return Promise.resolve(json(plans));
    return Promise.resolve(json({}));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("format client helpers", () => {
  it("writes percentages as exact fractions and reads fractions back", () => {
    expect(boxFromPercent(35, 20, 65, 80)).toEqual({ x0: "3500/10000", y0: "2000/10000", x1: "6500/10000", y1: "8000/10000" });
    expect(boxValue({ x0: "2/5", y0: "0", x1: "175/512", y1: "1" })).toEqual({ x0: 0.4, y0: 0, x1: 175 / 512, y1: 1 });
  });
});

describe("Formats page", () => {
  it("shows each projection with its steps and the measured checks, and holds approval until both planes pass", async () => {
    render(<FormatsPage projectName="demo" />);

    const card = await screen.findByRole("article");
    expect(within(card).getByRole("heading", { name: "square-pad-1" })).toBeInTheDocument();
    expect(within(card).getByRole("img")).toBeInTheDocument();
    const steps = within(card).getByRole("list");
    const buttons = within(steps).getAllByRole("button");
    expect(buttons).toHaveLength(4);
    // Technical passed, semantic pending: preparing the approval is not offered yet.
    expect(buttons[3]).toBeDisabled();
    expect(within(card).getAllByRole("row")).toHaveLength(CHECKS.length + 1);
  });

  it("says what to do when no approved master exists", async () => {
    sources = [];
    plans = [];
    render(<FormatsPage projectName="demo" />);

    expect(await screen.findByText(/No approved video master|还没有已批准的视频母版|Chưa có video master/)).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("creates a plan after registering the standard profiles, then reloads", async () => {
    plans = [];
    routes["/m8/formats/plans"] = () => json(summary().plan);
    render(<FormatsPage projectName="demo" />);
    const textbox = await screen.findByRole("textbox");
    const submit = screen.getByRole("button", { name: /Create plan|创建方案|Tạo phương án/ });
    expect(submit).toBeDisabled();

    fireEvent.change(textbox, { target: { value: "  keep the speaker  " } });
    fireEvent.click(submit);

    await waitFor(() => expect(posted("/m8/formats/plans")).toHaveLength(1));
    expect(posted("/m8/formats/profiles")).toHaveLength(STANDARD_PROFILES.length);
    expect(posted("/m8/formats/overlays")).toHaveLength(1);
    expect(posted("/m8/formats/plans")[0]).toMatchObject({
      source_artifact_key: SOURCE.artifact_key,
      profile_ref: "vertical-9x16@1",
      constraint_ref: NO_OVERLAY.constraint_ref,
      kind: "PAD",
      focal: null,
      rationale: "keep the speaker",
    });
    await waitFor(() => expect(requests.filter((item) => item.url.endsWith("/m8/formats/sources")).length).toBe(2));
  });

  it("runs a blind review: both clips load, every item needs a verdict, then the review is sent", async () => {
    routes["/review-packets"] = () => json({ packet_id: "pk-1", rubric_version: "format-semantic@1", items: ITEMS });
    routes["/clips/A"] = () => new Response(new Blob(["a"]), { status: 200 });
    routes["/clips/B"] = () => new Response(new Blob(["b"]), { status: 200 });
    routes["/review-packets/pk-1/reviews"] = () => json({ passed: true });
    render(<FormatsPage projectName="demo" />);
    const card = await screen.findByRole("article");

    fireEvent.click(within(within(card).getByRole("list")).getAllByRole("button")[2]);
    const review = await within(card).findByRole("region");
    await waitFor(() => expect(review.querySelectorAll("video")).toHaveLength(2));
    const submit = within(review).getByRole("button", { name: /Submit review|提交审阅|Gửi review/ });
    expect(submit).toBeDisabled();

    for (const group of within(review).getAllByRole("radiogroup")) {
      fireEvent.click(within(group).getAllByRole("radio")[0]);
    }
    fireEvent.click(submit);

    await waitFor(() => expect(posted("/review-packets/pk-1/reviews")).toHaveLength(1));
    expect(posted("/review-packets/pk-1/reviews")[0]).toEqual({ items: Object.fromEntries(ITEMS.map((item) => [item, "PASS"])), note: "" });
  });

  it("shows why a review could not be opened instead of waiting forever", async () => {
    routes["/review-packets"] = () =>
      json({ detail: "Only a reviewer with a current showrunner grant for this project can review projections" }, 403);
    render(<FormatsPage projectName="demo" />);
    const card = await screen.findByRole("article");

    fireEvent.click(within(within(card).getByRole("list")).getAllByRole("button")[2]);

    expect(await within(card).findByRole("alert")).toHaveTextContent(/showrunner grant/);
    expect(within(card).queryByRole("radiogroup")).not.toBeInTheDocument();
  });

  it("prepares, previews and approves a projection with the digest the server returned", async () => {
    plans = [summary({ semantic: { report_id: "sem-1", artifact_digest: "sha256:a", reviews: [], material_disagreement: false, passed: true } })];
    routes["/renders/exec-1/candidate"] = () =>
      json({ candidate_id: "format:square-pad-1", revision: 1, head_version: 1, slot_key: "m8-format:abc:square-1x1@1", expected_target_version: 0 });
    routes["/m8/formats/previews"] = () =>
      json({ preview: { preview_id: "pv-1", expires_at: "2999-01-01T00:00:00Z", impact: {} }, preview_digest: "sha256:pv" });
    routes["/m8/formats/promotions"] = () =>
      json({ receipt_id: "rc-1", result_artifact_ref: "m8-format:abc:square-1x1@1", result_digest: "sha256:a", promoted_at: "2026-10-14T00:00:00Z" });
    render(<FormatsPage projectName="demo" />);
    const card = await screen.findByRole("article");

    fireEvent.click(within(within(card).getByRole("list")).getAllByRole("button")[3]);
    const promotion = await within(card).findByRole("region", { name: /Approve this projection|批准该投影|Duyệt bản chiếu này/ });
    fireEvent.click(within(promotion).getByRole("button"));
    await waitFor(() => expect(posted("/m8/formats/previews")).toHaveLength(1));
    expect(posted("/m8/formats/previews")[0]).toMatchObject({ candidate_id: "format:square-pad-1", revision: 1, expected_target_version: 0 });

    fireEvent.click(await within(promotion).findByRole("button", { name: /^(Approve|批准|Duyệt)$/ }));
    expect(await within(promotion).findByRole("status")).toBeInTheDocument();
    expect(posted("/m8/formats/promotions")[0]).toMatchObject({
      preview_id: "pv-1",
      preview_digest: "sha256:pv",
      expected_candidate_head_version: 1,
    });
  });

  it("retries a render with the same command after an unknown outcome and with a new one after a refusal", async () => {
    const outcomes = [json({ detail: "server error" }, 500), json({ detail: "render failed" }, 409)];
    routes["/plans/square-pad-1/renders"] = () => outcomes.shift() ?? json({ execution_id: "exec-2", plan_id: "square-pad-1", artifact_digest: "sha256:b", replayed: false });
    render(<FormatsPage projectName="demo" />);
    const card = await screen.findByRole("article");
    const renderButton = () => within(within(card).getByRole("list")).getAllByRole("button")[0];

    for (let attempt = 1; attempt <= 3; attempt += 1) {
      await waitFor(() => expect(renderButton()).toBeEnabled());
      fireEvent.click(renderButton());
      await waitFor(() => expect(posted("/plans/square-pad-1/renders")).toHaveLength(attempt));
    }
    const commands = posted("/plans/square-pad-1/renders").map((body) => body.command_id);
    expect(commands[1]).toBe(commands[0]);
    expect(commands[2]).not.toBe(commands[1]);
  });
});
