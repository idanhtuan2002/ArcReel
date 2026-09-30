import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CanvasNode } from "../domain/types";
import { writeConflictSnapshot, type ConflictSnapshot } from "./draftRecovery";
import { hasUnstoredKeptAside, keepAside, readKeptAside, resetKeptAsideMemory, settleKeptAside } from "./keptAside";

const SCOPE = { userId: "u1", projectName: "p", candidateId: "c" };

function version(label: string, at: number): ConflictSnapshot {
  const node: CanvasNode = { id: "a", type: "note", position: { x: 0, y: 0 }, data: { label } };
  return { nodes: [node], edges: [], viewport: null, metadata: null, timestamp: new Date(at).toISOString() };
}

const labels = () => readKeptAside(SCOPE).map((item) => item.snapshot.nodes[0].data.label);

describe("kept-aside versions", () => {
  beforeEach(() => {
    window.localStorage.clear();
    resetKeptAsideMemory();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps versions under their own keys, oldest first, with the legacy slot included", () => {
    writeConflictSnapshot(SCOPE, version("legacy", 1_000));
    keepAside(SCOPE, version("newest", 3_000));
    keepAside(SCOPE, version("middle", 2_000));

    expect(labels()).toEqual(["legacy", "middle", "newest"]);
    expect(readKeptAside({ ...SCOPE, candidateId: "other" })).toEqual([]);
  });

  it("does not keep the same version twice", () => {
    keepAside(SCOPE, version("same", 1_000));
    keepAside(SCOPE, version("same", 2_000));

    expect(labels()).toEqual(["same"]);
  });

  it("holds a version in memory when storage refuses it, and reports that", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("unavailable", "SecurityError");
    });

    const held = keepAside(SCOPE, version("memory", 1_000));

    expect(held.key).toBeNull();
    expect(labels()).toEqual(["memory"]);
    expect(hasUnstoredKeptAside()).toBe(true);

    settleKeptAside(SCOPE, held);
    expect(labels()).toEqual([]);
    expect(hasUnstoredKeptAside()).toBe(false);
  });

  it("removes a settled stored version and leaves the others", () => {
    const first = keepAside(SCOPE, version("first", 1_000));
    keepAside(SCOPE, version("second", 2_000));

    settleKeptAside(SCOPE, first);

    expect(labels()).toEqual(["second"]);
  });
});
