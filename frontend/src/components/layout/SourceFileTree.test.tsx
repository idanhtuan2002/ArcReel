import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";

import i18n from "@/i18n";
import { SourceFileTree } from "./SourceFileTree";

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

describe("SourceFileTree", () => {
  it("lists the files, marks the one the URL opens and leads to the upload page", () => {
    const location = memoryLocation({ path: "/source/Ch%C6%B0%C6%A1ng%202.txt", record: true });
    render(
      <Router hook={location.hook}>
        <SourceFileTree files={["Chương 1.txt", "Chương 2.txt"]} />
      </Router>,
    );

    expect(screen.getByRole("button", { name: "Chương 2.txt" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Chương 1.txt" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("button", { name: "Upload source files" })).not.toHaveAttribute("aria-current");

    fireEvent.click(screen.getByRole("button", { name: "Chương 1.txt" }));
    expect(location.history?.at(-1)).toBe("/source/Ch%C6%B0%C6%A1ng%201.txt");

    fireEvent.click(screen.getByRole("button", { name: "Upload source files" }));
    expect(location.history?.at(-1)).toBe("/source");
  });

  it("says when the project has no source files", () => {
    const location = memoryLocation({ path: "/source" });
    render(
      <Router hook={location.hook}>
        <SourceFileTree files={[]} />
      </Router>,
    );

    expect(screen.getByRole("button", { name: "Upload source files" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("No source files yet.")).toBeInTheDocument();
  });
});
