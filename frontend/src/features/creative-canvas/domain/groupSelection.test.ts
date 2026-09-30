// Donor tests (DramaClaw b299bfd9: __tests__/features/canvas/group-selection-delete.test.ts and
// group-selection-duplicate.test.ts) run on the port, with donor node types mapped to port types.
// The donor cases about preset-managed locks are omitted: the ArcReel Canvas has no such locks.
import { describe, expect, it } from "vitest";

import {
  collectBatchDeletableIds,
  collectDuplicableIds,
} from "./groupSelection";
import type { CanvasNode } from "./types";

function node(
  id: string,
  type: CanvasNode["type"],
  extra: Partial<CanvasNode> = {},
): CanvasNode {
  return { id, type, position: { x: 0, y: 0 }, data: {}, ...extra };
}

function member(
  id: string,
  parentId: string,
  extra: Partial<CanvasNode> = {},
): CanvasNode {
  return node(id, "frame", { parentId, extent: "parent", ...extra });
}

describe("collectBatchDeletableIds", () => {
  it("re-includes an enclosing group when all its children are selected (the empty-group bug)", () => {
    const nodes = [
      node("g1", "group"),
      node("a", "audio", { parentId: "g1" }),
      node("b", "note", { parentId: "g1" }),
    ];

    expect(new Set(collectBatchDeletableIds(nodes, ["a", "b"]))).toEqual(
      new Set(["g1", "a", "b"]),
    );
  });

  it("handles two fully-selected groups", () => {
    const nodes = [
      node("g1", "group"),
      node("a", "audio", { parentId: "g1" }),
      node("g2", "group"),
      node("c", "audio", { parentId: "g2" }),
      node("d", "note", { parentId: "g2" }),
    ];

    expect(new Set(collectBatchDeletableIds(nodes, ["a", "c", "d"]))).toEqual(
      new Set(["g1", "g2", "a", "c", "d"]),
    );
  });

  it("does not delete a group when only some of its children are selected", () => {
    const nodes = [
      node("g1", "group"),
      node("a", "audio", { parentId: "g1" }),
      node("b", "note", { parentId: "g1" }),
    ];

    expect(new Set(collectBatchDeletableIds(nodes, ["a"]))).toEqual(
      new Set(["a"]),
    );
  });

  it("passes a plain multi-selection through unchanged", () => {
    expect(
      new Set(
        collectBatchDeletableIds(
          [node("a", "audio"), node("b", "frame")],
          ["a", "b"],
        ),
      ),
    ).toEqual(new Set(["a", "b"]));
  });
});

describe("collectDuplicableIds", () => {
  it("adds back a whole-selected group, before its members", () => {
    const nodes = [node("g", "group"), member("m1", "g"), member("m2", "g")];

    expect(collectDuplicableIds(nodes, ["m1", "m2"])).toEqual([
      "g",
      "m1",
      "m2",
    ]);
  });

  it("keeps parent-first order when the group is selected explicitly", () => {
    expect(
      collectDuplicableIds(
        [node("g", "group"), member("m1", "g")],
        ["m1", "g"],
      ),
    ).toEqual(["g", "m1"]);
  });

  it("does not add the group when only some members are selected", () => {
    const nodes = [node("g", "group"), member("m1", "g"), member("m2", "g")];

    expect(collectDuplicableIds(nodes, ["m1"])).toEqual(["m1"]);
  });

  it("resolves nested groups inner first and returns pre-order", () => {
    const nodes = [
      node("outer", "group"),
      node("inner", "group", { parentId: "outer", extent: "parent" }),
      member("m1", "inner"),
      member("m2", "inner"),
    ];

    expect(collectDuplicableIds(nodes, ["m1", "m2"])).toEqual([
      "outer",
      "inner",
      "m1",
      "m2",
    ]);
  });

  it("keeps explicitly selected nodes whatever their data", () => {
    const nodes = [
      node("a", "frame", { data: { preset_managed: true } }),
      node("b", "frame"),
    ];

    expect(collectDuplicableIds(nodes, ["a", "b"])).toEqual(["a", "b"]);
  });

  it("returns the selection in node order when there is no group", () => {
    expect(
      collectDuplicableIds(
        [node("a", "frame"), node("b", "frame")],
        ["b", "a"],
      ),
    ).toEqual(["a", "b"]);
  });
});
