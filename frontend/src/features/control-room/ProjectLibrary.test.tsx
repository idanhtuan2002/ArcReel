import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";

import { API } from "@/api";
import i18n from "@/i18n";
import { ProjectLibrary } from "./ProjectLibrary";

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

function row(name: string) {
  return { name, title: name, style: "", thumbnail: null, status: {}, project_kind: "film" as const, updated_at: null };
}

describe("ProjectLibrary", () => {
  it("moves back to the last page that has rows when a delete empties the current page", async () => {
    let total = 51;
    vi.spyOn(API, "projectIndex").mockImplementation((query = {}) => {
      const offset = query.offset ?? 0;
      const items = offset === 0 ? [row("first-page")] : offset < total ? [row("last-row")] : [];
      return Promise.resolve({ total, counts: { all: total, story: 0, film: total }, offset, limit: 50, items });
    });
    const location = memoryLocation({ path: "/app/projects" });
    const view = (reload: number) => (
      <Router hook={location.hook}>
        <ProjectLibrary search="" reload={reload} onDelete={() => undefined} onCreate={() => undefined} />
      </Router>
    );
    const { rerender } = render(view(0));
    await screen.findByRole("link", { name: "first-page" });
    screen.getByRole("button", { name: /Next/ }).click();
    await screen.findByRole("link", { name: "last-row" });

    total = 50; // the last row was deleted
    rerender(view(1));

    expect(await screen.findByRole("link", { name: "first-page" })).toBeInTheDocument();
    expect(screen.queryByText("No projects yet.")).not.toBeInTheDocument();
  });
});
