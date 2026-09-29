import { describe, expect, it } from "vitest";

import { createEmptyBookmarks } from "../domain/bookmarks";
import type { CanvasEdge, CanvasNode } from "../domain/types";
import { canonicalJson } from "./canonical";
import { fromCanvasPayload, toCanvasPayload } from "./serialize";

const board: CanvasNode = {
  id: "g1",
  type: "group",
  position: { x: 10, y: 20 },
  style: { width: 600, height: 400 },
  dragHandle: ".storyboard-handle",
  data: { label: "Storyboard 1", storyboardGroup: true },
};
const second: CanvasNode = { id: "f2", type: "frame", position: { x: 300, y: 0 }, parentId: "g1", hidden: true, data: { assetRef: "b.png" } };
const first: CanvasNode = { id: "f1", type: "frame", position: { x: 0, y: 0 }, parentId: "g1", hidden: true, data: { assetRef: "a.png" } };
const beat: CanvasNode = {
  id: "b1",
  type: "beat",
  position: { x: -40.5, y: 12.25 },
  width: 440,
  height: 320,
  selected: true,
  measured: { width: 440, height: 320 },
  data: { label: "Mở đầu", note: undefined },
};
const edges: CanvasEdge[] = [
  { id: "e1", source: "b1", target: "g1" },
  { id: "e2", source: "b1", target: "f1", type: "smoothstep", sourceHandle: "out", data: { label: "cut" } },
];

describe("canvas payload", () => {
  it("projects groups and the storyboard reading order", () => {
    const payload = toCanvasPayload([board, second, first, beat], edges, createEmptyBookmarks());

    expect(payload.groups).toEqual([{ group_id: "g1", member_ids: ["f1", "f2"], storyboard: true }]);
    expect(payload.storyboard_order).toEqual(["f1", "f2"]);
  });

  it("keeps persistent fields and drops view state", () => {
    const payload = toCanvasPayload([beat], [], createEmptyBookmarks());

    expect(payload.nodes).toEqual([
      {
        node_id: "b1",
        node_type: "beat",
        body: { position: { x: -40.5, y: 12.25 }, width: 440, height: 320, data: { label: "Mở đầu" } },
      },
    ]);
  });

  it("round-trips the graph and bookmarks through the wire", () => {
    const bookmarks = createEmptyBookmarks();
    bookmarks[3] = { x: 1.5, y: -2, zoom: 0.35 };
    const payload = JSON.parse(JSON.stringify(toCanvasPayload([board, second, first, beat], edges, bookmarks)));

    const loaded = fromCanvasPayload(payload);

    const { selected: _selected, measured: _measured, ...savedBeat } = beat;
    expect(loaded.nodes).toEqual([board, second, first, { ...savedBeat, data: { label: "Mở đầu" } }]);
    expect(loaded.edges).toEqual(edges);
    expect(loaded.bookmarks).toEqual(bookmarks);
  });

  it("is canonical-encodable as the save digest needs", () => {
    const payload = toCanvasPayload([board, second, first, beat], edges, createEmptyBookmarks());

    expect(() => canonicalJson(payload)).not.toThrow();
  });

  it("skips nodes of an unknown type with their edges, and malformed bookmarks", () => {
    const payload = toCanvasPayload([beat], [], createEmptyBookmarks());
    payload.nodes.push({ node_id: "x", node_type: "generator", body: { position: { x: 0, y: 0 }, data: {} } });
    payload.edges.push({ edge_id: "ex", source_node_id: "b1", target_node_id: "x", edge_type: "default", body: {} });
    payload.viewport_bookmarks.push({ slot: 12, x: 0, y: 0, zoom: 1 }, { slot: 1, x: "0", y: 0, zoom: 1 });

    const loaded = fromCanvasPayload(payload);

    expect(loaded.nodes.map((node) => node.id)).toEqual(["b1"]);
    expect(loaded.edges).toEqual([]);
    expect(loaded.bookmarks).toEqual(createEmptyBookmarks());
  });
});
