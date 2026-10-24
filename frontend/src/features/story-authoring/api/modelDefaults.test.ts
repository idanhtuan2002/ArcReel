import { describe, expect, it } from "vitest";
import { resolveStoryDefaults } from "./modelDefaults";
import type { StoryRoute } from "./storyClient";
const routes: StoryRoute[] = ["local/a", "cloud/b", "cloud/c"].map((key) => ({
  provider_id: key.split("/")[0],
  model_id: key.split("/")[1],
  label: key,
  enabled: true,
  reason: null,
  cloud: key.startsWith("cloud"),
}));
describe("story model inheritance", () => {
  it.each([
    [
      { text_backend_complex: "cloud/b", default_text_backend: "local/a" },
      { text_backend_complex: "cloud/c" },
      "cloud/b",
      "project",
    ],
    [{ default_text_backend: "local/a" }, { text_backend_complex: "cloud/c" }, "local/a", "project"],
    [{}, { text_backend_complex: "cloud/c", default_text_backend: "cloud/b" }, "cloud/c", "system"],
    [{}, { default_text_backend: "cloud/b" }, "cloud/b", "system"],
    [{}, {}, "local/a", "automatic"],
  ])("respects existing text precedence", (project, system, writer, source) => {
    expect(resolveStoryDefaults(routes, project, system)).toMatchObject({ writer, source, available: true });
  });
  it("does not replace an explicitly inherited unavailable model", () => {
    expect(resolveStoryDefaults(routes, { default_text_backend: "missing/model" }, {})).toEqual({
      writer: "missing/model",
      source: "project",
      available: false,
    });
  });
});
