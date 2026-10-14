import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { relativeLift, type ArmSummary, type RecommendationView } from "../api/learningClient";
import LearningPage from "./LearningPage";

const ARMS: ArmSummary[] = [
  { arm: "16x9", n: 3, present: 3, missing: {}, mean: "100", median: "100", min: "100", max: "100", observation_ids: ["a1"] },
  { arm: "9x16", n: 4, present: 3, missing: { PRIVATE: 1 }, mean: "80", median: "80", min: "80", max: "80", observation_ids: ["b1"] },
];

const VIEW: RecommendationView = {
  recommendation: {
    recommendation_id: "rec-1",
    evidence_observation_ids: ["a1", "b1"],
    hypothesis: "Format 9x16 is associated with 20.0% lower mean views than format 16x9.",
    applicability: { summaries: ARMS, arms: ["16x9", "9x16"] },
    exclusions: ["9x16: 1 PRIVATE"],
    confidence: 6 / 7,
    expected_guardrails: [],
    expires_at: "2999-01-01T00:00:00Z",
  },
  recommendation_digest: "sha256:rec",
  language: "associative",
  rule: "compare_cohorts@1",
  evidence_cutoff: "2026-10-14T00:00:00Z",
  created_at: "2026-10-14T00:00:00Z",
  decisions: [],
  final: false,
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let listed: RecommendationView[] = [];
let decideResponse: () => Response = () => json({});
let evaluateResponse: () => Response = () => json({});
const requests: { url: string; body: unknown }[] = [];

beforeEach(() => {
  listed = [VIEW];
  requests.length = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    requests.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url.endsWith("/m8/learning/recommendations")) return Promise.resolve(json(listed));
    if (url.endsWith("/recommendations/evaluate")) return Promise.resolve(evaluateResponse());
    if (url.endsWith("/decisions")) return Promise.resolve(decideResponse());
    return Promise.resolve(json({}, 404));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("relativeLift", () => {
  it("is the signed change of B over A and null without a usable baseline", () => {
    expect(relativeLift(ARMS)).toBeCloseTo(-0.2);
    expect(relativeLift([{ ...ARMS[0], mean: "0" }, ARMS[1]])).toBeNull();
    expect(relativeLift([ARMS[0]])).toBeNull();
  });
});

describe("Learning page", () => {
  it("shows a recommendation with its evidence ledger and an associative badge", async () => {
    render(<LearningPage projectName="demo" />);

    const card = await screen.findByRole("article");
    expect(within(card).getByText("ASSOCIATIVE")).toBeInTheDocument();
    expect(within(card).getByText(VIEW.recommendation.hypothesis)).toBeInTheDocument();
    expect(within(card).getByText("−20.0%")).toBeInTheDocument();
    expect(within(card).getByText("3 / 4")).toBeInTheDocument();
  });

  it("records a decision only with a disposition and a reason, then reloads", async () => {
    decideResponse = () => json({ decision_id: "d" });
    render(<LearningPage projectName="demo" />);
    const card = await screen.findByRole("article");
    const submit = within(card).getByRole("button");
    expect(submit).toBeDisabled();

    fireEvent.click(within(card).getAllByRole("radio")[1]);
    fireEvent.change(within(card).getByRole("textbox"), { target: { value: "  sample too small  " } });
    fireEvent.click(submit);

    await waitFor(() => expect(requests.some((item) => item.url.endsWith("/decisions"))).toBe(true));
    const sent = requests.find((item) => item.url.endsWith("/recommendations/rec-1/decisions"))?.body as Record<string, unknown>;
    expect(sent).toMatchObject({
      disposition: "REJECT",
      expected_recommendation_digest: "sha256:rec",
      reason: "sample too small",
    });
    await waitFor(() => expect(requests.filter((item) => item.url.endsWith("/m8/learning/recommendations")).length).toBe(2));
  });

  it("shows the server's refusal when a decision is stale", async () => {
    decideResponse = () => json({ detail: "This recommendation expired, changed, or its evidence was corrected" }, 409);
    render(<LearningPage projectName="demo" />);
    const card = await screen.findByRole("article");

    fireEvent.click(within(card).getAllByRole("radio")[0]);
    fireEvent.change(within(card).getByRole("textbox"), { target: { value: "ok" } });
    fireEvent.click(within(card).getByRole("button"));

    expect(await within(card).findByRole("alert")).toHaveTextContent(/evidence was corrected/);
  });

  it("hides the decision form once a final decision exists", async () => {
    listed = [{ ...VIEW, final: true, decisions: [{ decision_id: "d", recommendation_id: "rec-1", disposition: "ACCEPT", actor_id: "reviewer-a", reason: "fits", governed_proposal_ref: "learning-proposal:d", decided_at: "2026-10-14T01:00:00Z" }] }];
    render(<LearningPage projectName="demo" />);
    const card = await screen.findByRole("article");

    expect(within(card).queryByRole("radio")).not.toBeInTheDocument();
    expect(within(card).getByText("learning-proposal:d")).toBeInTheDocument();
  });

  it("runs a comparison and reports why nothing was proposed", async () => {
    listed = [];
    evaluateResponse = () =>
      json({ fired: false, reason: "lift below threshold", relative_lift: "0.05", evidence_cutoff: null, arms: ARMS, recommendation: null });
    render(<LearningPage projectName="demo" />);
    await screen.findByText(/No recommendations yet|还没有建议|Chưa có đề xuất/);

    const form = screen.getByRole("button", { name: /Run comparison|运行比较|Chạy so sánh/ }).closest("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form as HTMLFormElement);

    const status = await screen.findByRole("status", {}, { timeout: 2000 });
    await waitFor(() => expect(status).toHaveTextContent(/below the minimum|低于最小值|thấp hơn mức tối thiểu/));
    const sent = requests.find((item) => item.url.endsWith("/recommendations/evaluate"))?.body as Record<string, unknown>;
    expect(sent).toMatchObject({ arm_a: "16x9", arm_b: "9x16", min_per_arm: 3, min_relative_lift: "0.10" });
    expect(typeof sent.command_id).toBe("string");
  });
});
