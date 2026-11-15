import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

import type { AudiobookJob } from "../api/storyClient";
import { AudiobookPanel } from "./AudiobookPanel";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

let jobs: AudiobookJob[] = [];
const posts: { url: string; body: unknown }[] = [];

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

afterAll(async () => {
  await i18n.changeLanguage("zh");
});

beforeEach(() => {
  jobs = [];
  posts.length = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if ((init?.method ?? "GET") === "POST" && url.endsWith("/story-runs/story-1/audiobook")) {
      const body = JSON.parse(String(init?.body)) as { preset: AudiobookJob["preset"] };
      posts.push({ url, body });
      jobs = [{ run_id: "story-1", preset: body.preset, state: "running", done: 3, total: 40, error: null, duration: null, files: [] }];
      return Promise.resolve(json(jobs[0]));
    }
    if (url.endsWith("/story-runs/story-1/audiobook")) return Promise.resolve(json({ jobs }));
    return Promise.resolve(json({}));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("audiobook panel", () => {
  it("starts a sleep story and shows its progress", async () => {
    render(<AudiobookPanel projectName="demo" runId="story-1" title="Đò" />);

    fireEvent.click(await screen.findByRole("button", { name: "Create sleep story" }));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].body).toEqual({ preset: "sleep" });
    expect(await screen.findByText("Reading 3/40 segments")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create sleep story" })).toBeDisabled();
  });

  it("offers the files of a finished audiobook", async () => {
    jobs = [
      { run_id: "story-1", preset: "standard", state: "done", done: 40, total: 40, error: null, duration: 612, files: ["m4b", "mp3", "chapters"] },
    ];
    render(<AudiobookPanel projectName="demo" runId="story-1" title="Đò" />);

    expect(await screen.findByRole("button", { name: "Download M4B (chapters)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download MP3" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Chapter timestamps" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Download MP4 (YouTube)" })).not.toBeInTheDocument();
  });
});
