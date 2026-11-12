import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";

import * as storyClient from "@/features/story-authoring/api/storyClient";
import { announceStoryRunsChanged } from "@/features/story-authoring/ui/StoryAuthoringPage";
import i18n from "@/i18n";
import { StoryRunTree } from "./StoryRunTree";

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

const run = (run_id: string, idea: string, phase: storyClient.RunSummary["phase"] = "RUNNING") => ({
  run_id,
  idea,
  phase,
  genre: "g",
  started_at: "2026-11-10T00:00:00Z",
});

describe("StoryRunTree", () => {
  it("lists the stories, marks the one the URL names and opens the new-story form", async () => {
    const list = vi.spyOn(storyClient, "listRuns").mockResolvedValue([
      { ...run("a", "Bến đò"), book_part: 2 },
      run("b", "Chợ đêm", "COMMITTED"),
    ]);
    const location = memoryLocation({ path: "/story", searchPath: "run=b", record: true });
    render(
      <Router hook={location.hook} searchHook={location.searchHook}>
        <StoryRunTree projectName="demo" />
      </Router>,
    );

    expect(await screen.findByRole("button", { name: /Chợ đêm/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: /Bến đò/ })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("button", { name: /Bến đò/ })).toHaveTextContent("Part 2 · Bến đò");

    fireEvent.click(screen.getByRole("button", { name: "New story" }));
    expect(location.history?.at(-1)).toBe("/story?new=1");

    fireEvent.click(screen.getByRole("button", { name: /Bến đò/ }));
    expect(location.history?.at(-1)).toBe("/story?run=a");

    announceStoryRunsChanged();
    expect(list).toHaveBeenCalledTimes(2);
  });
});
