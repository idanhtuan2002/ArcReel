import { afterEach, describe, expect, it, vi } from "vitest";

import { greenlightAndStart, listRoutes, type StoryBrief } from "./storyClient";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("story client", () => {
  it("loads backend story routes including configured cloud models without rebuilding a local-only list", async () => {
    const routes = [
      {
        provider_id: "gemini-aistudio",
        model_id: "gemini-2.5-flash",
        label: "Gemini Flash",
        enabled: true,
        reason: null,
        cloud: true,
      },
    ];
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ routes }));
    expect(await listRoutes()).toEqual(routes);
    expect(String(fetch.mock.calls[0][0])).toContain("/system/config/story-routes");
  });

  it("starts a run under the greenlight of the exact brief digest", async () => {
    const calls: { url: string; body: unknown }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      calls.push({ url: String(input), body: JSON.parse(String(init?.body)) });
      return Promise.resolve(
        String(input).endsWith("/greenlight") ? json({ decision_id: "d-1" }) : json({ run_id: "story-9" }),
      );
    });
    const brief = { idea: "i" } as unknown as StoryBrief;

    const runId = await greenlightAndStart("demo project", { brief, brief_digest: "sha256:b" });

    expect(runId).toBe("story-9");
    expect(calls.map((call) => call.url.replace(/^.*\/api\/v1/, ""))).toEqual([
      "/projects/demo%20project/gates/greenlight",
      "/projects/demo%20project/story-runs",
    ]);
    expect(calls[0].body).toEqual({ source_digest: "sha256:b", action: "GREENLIGHT" });
    expect(calls[1].body).toEqual({ brief, gate_a_decision_id: "d-1" });
  });
});
