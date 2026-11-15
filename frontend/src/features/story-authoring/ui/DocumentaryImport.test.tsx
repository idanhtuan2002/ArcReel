import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";

import type { DocumentaryJob } from "../api/storyClient";
import { DocumentaryImport } from "./DocumentaryImport";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

let jobs: DocumentaryJob[] = [];
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
    if ((init?.method ?? "GET") === "POST" && url.endsWith("/projects/demo/documentaries")) {
      const body = JSON.parse(String(init?.body)) as {
        topic: string;
        language: DocumentaryJob["language"];
        form: DocumentaryJob["form"];
      };
      posts.push(body);
      jobs = [{ topic: body.topic, language: body.language, form: body.form, state: "done", error: null, source: "source/x.txt", title: "Cây cầu", claims: 40 }];
      return Promise.resolve(json(jobs[0]));
    }
    if (url.endsWith("/projects/demo/documentaries")) return Promise.resolve(json({ jobs }));
    return Promise.resolve(json({}));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("documentary import", () => {
  it("starts a documentary in the chosen language and reports the sourced facts", async () => {
    render(<DocumentaryImport projectName="demo" />);

    fireEvent.change(screen.getByPlaceholderText("e.g. Long Bien Bridge"), { target: { value: "Cầu Long Biên" } });
    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "en" } });
    fireEvent.change(screen.getByLabelText("Form"), { target: { value: "quiz" } });
    fireEvent.click(screen.getByRole("button", { name: "Write narration" }));

    await waitFor(() => expect(posts).toEqual([{ topic: "Cầu Long Biên", language: "en", form: "quiz" }]));
    expect(await screen.findByText("Cây cầu: added to sources (40 sourced facts)")).toBeInTheDocument();
  });
});
