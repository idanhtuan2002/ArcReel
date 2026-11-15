import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

import type { VideoSourceJob } from "../api/storyClient";
import { VideoSourceImport } from "./VideoSourceImport";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

let jobs: VideoSourceJob[] = [];
const posts: unknown[] = [];

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
    if ((init?.method ?? "GET") === "POST" && url.endsWith("/projects/demo/video-sources")) {
      const body = JSON.parse(String(init?.body)) as { url: string };
      posts.push(body);
      jobs = [{ url: body.url, state: "running", step: "transcribe", error: null, source: null, title: "Ông lái đò" }];
      return Promise.resolve(json(jobs[0]));
    }
    if (url.endsWith("/projects/demo/video-sources")) return Promise.resolve(json({ jobs }));
    return Promise.resolve(json({}));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("video source import", () => {
  it("imports a URL and shows the job's step", async () => {
    render(<VideoSourceImport projectName="demo" />);

    fireEvent.change(screen.getByPlaceholderText("https://"), { target: { value: "https://example.com/v/1" } });
    fireEvent.click(screen.getByRole("button", { name: "Import" }));

    await waitFor(() => expect(posts).toEqual([{ url: "https://example.com/v/1" }]));
    expect(await screen.findByText("Ông lái đò: transcribing")).toBeInTheDocument();
  });
});
