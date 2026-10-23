import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NARROW_VIEWPORT_QUERY, useNarrowViewport } from "./useNarrowViewport";

function mockMatchMedia(initial: boolean) {
  const listeners = new Set<() => void>();
  const media = {
    matches: initial,
    media: NARROW_VIEWPORT_QUERY,
    addEventListener: (_: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
  };
  vi.stubGlobal("matchMedia", vi.fn(() => media));
  return {
    set(next: boolean) {
      media.matches = next;
      listeners.forEach((listener) => listener());
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("useNarrowViewport", () => {
  it("follows the narrow-viewport media query", () => {
    const control = mockMatchMedia(true);
    const { result } = renderHook(() => useNarrowViewport());
    expect(result.current).toBe(true);
    act(() => control.set(false));
    expect(result.current).toBe(false);
  });

  it("is false where matchMedia is unavailable", () => {
    vi.stubGlobal("matchMedia", undefined);
    const { result } = renderHook(() => useNarrowViewport());
    expect(result.current).toBe(false);
  });
});
