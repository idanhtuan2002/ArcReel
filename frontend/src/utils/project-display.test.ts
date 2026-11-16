import { describe, expect, it } from "vitest";
import { getProjectDisplayName } from "./project-display";

describe("getProjectDisplayName", () => {
  const UNTITLED = "未命名项目";

  it("falls back when title is null / undefined / empty / whitespace", () => {
    expect(getProjectDisplayName(undefined, UNTITLED)).toBe(UNTITLED);
    expect(getProjectDisplayName(null, UNTITLED)).toBe(UNTITLED);
    expect(getProjectDisplayName("", UNTITLED)).toBe(UNTITLED);
    expect(getProjectDisplayName("   ", UNTITLED)).toBe(UNTITLED);
    expect(getProjectDisplayName("\t\n", UNTITLED)).toBe(UNTITLED);
  });

  it("returns trimmed title when non-empty", () => {
    expect(getProjectDisplayName("第一集", UNTITLED)).toBe("第一集");
    expect(getProjectDisplayName("  第一集  ", UNTITLED)).toBe("第一集");
    expect(getProjectDisplayName("My Novel", UNTITLED)).toBe("My Novel");
  });

  it("respects caller-provided untitled label across locales", () => {
    expect(getProjectDisplayName(undefined, "Untitled Project")).toBe("Untitled Project");
    expect(getProjectDisplayName("", "Dự án chưa đặt tên")).toBe("Dự án chưa đặt tên");
  });
});

describe("getProjectDisplayName with Markdown titles", () => {
  it("reads a title written as a Markdown heading without its marks", () => {
    expect(getProjectDisplayName("# MÊ CUNG DỤC VỌNG", "x")).toBe("MÊ CUNG DỤC VỌNG");
    expect(getProjectDisplayName("## Chuyến đò cuối ", "x")).toBe("Chuyến đò cuối");
    expect(getProjectDisplayName("C# và #hashtag", "x")).toBe("C# và #hashtag");
    expect(getProjectDisplayName("# MÊ CUNG DỤC VỌNG ### LABYRINTH OF DESIRE", "x")).toBe(
      "MÊ CUNG DỤC VỌNG · LABYRINTH OF DESIRE",
    );
    expect(getProjectDisplayName("  #  ", "Chưa đặt tên")).toBe("Chưa đặt tên");
  });
});
