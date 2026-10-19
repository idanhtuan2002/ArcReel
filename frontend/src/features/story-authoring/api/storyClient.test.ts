import { afterEach, describe, expect, it, vi } from "vitest";

import type { CustomProviderInfo } from "@/types";

import { greenlightAndStart, storyRoutes, type StoryBrief } from "./storyClient";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("story client", () => {
  it("lists only enabled models on the native Ollama chat endpoint as story routes", () => {
    const provider = {
      id: 3,
      display_name: "Ollama",
      models: [
        { model_id: "a", display_name: "A", endpoint: "ollama-chat", is_enabled: true },
        { model_id: "b", display_name: "", endpoint: "ollama-chat", is_enabled: false },
        { model_id: "c", display_name: "", endpoint: "openai-chat", is_enabled: true },
      ],
    } as unknown as CustomProviderInfo;

    expect(storyRoutes([provider])).toEqual([{ provider_id: "custom-3", model_id: "a", label: "Ollama · A" }]);
  });

  it("starts a run under the greenlight of the exact brief digest", async () => {
    const calls: { url: string; body: unknown }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      calls.push({ url: String(input), body: JSON.parse(String(init?.body)) });
      return Promise.resolve(String(input).endsWith("/greenlight") ? json({ decision_id: "d-1" }) : json({ run_id: "story-9" }));
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
