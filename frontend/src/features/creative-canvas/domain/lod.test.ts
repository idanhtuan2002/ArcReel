// Ported from the donor tests (DramaClaw b299bfd9,
// __tests__/features/canvas/canvas-lod.test.ts: isLowDetailZoom and the media-active signal).
import { describe, expect, it } from "vitest";

import { LOW_DETAIL_ZOOM_THRESHOLD, isLowDetailZoom, isNodeMediaActive, setNodeMediaActive } from "./lod";

describe("isLowDetailZoom", () => {
  it("is low detail only below the threshold, not at it", () => {
    expect(isLowDetailZoom(LOW_DETAIL_ZOOM_THRESHOLD - 0.01)).toBe(true);
    expect(isLowDetailZoom(LOW_DETAIL_ZOOM_THRESHOLD)).toBe(false);
    expect(isLowDetailZoom(LOW_DETAIL_ZOOM_THRESHOLD + 0.01)).toBe(false);
  });

  it("leaves the working zoom range (0.5 to 1) alone", () => {
    expect(isLowDetailZoom(0.5)).toBe(false);
    expect(isLowDetailZoom(1)).toBe(false);
  });

  it("treats non-finite zoom as full detail", () => {
    expect(isLowDetailZoom(Number.NaN)).toBe(false);
    expect(isLowDetailZoom(Number.POSITIVE_INFINITY)).toBe(false);
    expect(isLowDetailZoom(Number.NEGATIVE_INFINITY)).toBe(false);
  });
});

describe("node media active signal", () => {
  it("marks, clears and queries consistently", () => {
    expect(isNodeMediaActive("n1")).toBe(false);
    setNodeMediaActive("n1", true);
    expect(isNodeMediaActive("n1")).toBe(true);
    expect(isNodeMediaActive("n2")).toBe(false);
    setNodeMediaActive("n1", false);
    expect(isNodeMediaActive("n1")).toBe(false);
  });

  it("clears idempotently (unmount cleanup and pause can both fire)", () => {
    setNodeMediaActive("n1", true);
    setNodeMediaActive("n1", false);
    setNodeMediaActive("n1", false);
    expect(isNodeMediaActive("n1")).toBe(false);
  });
});
