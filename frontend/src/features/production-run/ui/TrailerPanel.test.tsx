import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import i18n from "@/i18n";
import type { TrailerJob } from "../api/productionRunClient";
import { TrailerPanel } from "./TrailerPanel";

describe("TrailerPanel", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    await i18n.changeLanguage("zh");
  });

  it("starts a trailer and offers the finished one", async () => {
    let job: TrailerJob | null = null;
    const posts: string[] = [];
    vi.spyOn(API, "request").mockImplementation(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push(path);
        job = { run_id: "r1", state: "done", error: null, duration: 31.6, started_at: "2026-11-15T00:00:00Z" };
        return job;
      }
      return { job };
    });

    render(<TrailerPanel projectName="p" runId="r1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Make trailer" }));

    await waitFor(() => expect(posts).toEqual(["/projects/p/production-runs/r1/trailer"]));
    expect(await screen.findByRole("button", { name: "Download trailer (32 s)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make trailer again" })).toBeInTheDocument();
  });
});
