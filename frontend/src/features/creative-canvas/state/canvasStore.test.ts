import { beforeEach, describe, expect, it } from "vitest";

import { addNode, applyNodeChanges } from "../domain/graph";
import { useCanvasStore } from "./canvasStore";

const store = () => useCanvasStore.getState();

describe("canvas store", () => {
  beforeEach(() => {
    store().reset();
  });

  it("counts tracked edits but not selection or a drag in progress", () => {
    store().edit((graph) => addNode(graph, { id: "a", type: "note", position: { x: 0, y: 0 }, data: {} }));
    expect(store().editSeq).toBe(1);

    store().edit((graph) => applyNodeChanges(graph, [{ type: "select", id: "a", selected: true }]));
    store().edit((graph) =>
      applyNodeChanges(graph, [{ type: "position", id: "a", position: { x: 5, y: 5 }, dragging: true }]),
    );
    expect(store().editSeq).toBe(1);

    store().edit((graph) =>
      applyNodeChanges(graph, [{ type: "position", id: "a", position: { x: 9, y: 9 }, dragging: false }]),
    );
    expect(store().editSeq).toBe(2);
  });

  it("counts a bookmark change and leaves a replace uncounted", () => {
    store().editBookmarks((bookmarks) => bookmarks.map((item, index) => (index === 0 ? { x: 1, y: 2, zoom: 1 } : item)));
    store().replace({ phase: "ready" });

    expect(store().editSeq).toBe(1);
  });
});
