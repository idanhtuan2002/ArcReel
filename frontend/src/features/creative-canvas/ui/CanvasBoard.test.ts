import { describe, expect, it } from "vitest";

import { toDomainChanges } from "./CanvasBoard";

describe("React Flow node changes", () => {
  it("keeps the changes the domain handles and drops add and replace", () => {
    expect(
      toDomainChanges([
        { type: "position", id: "a", position: { x: 1, y: 2 }, dragging: true },
        { type: "dimensions", id: "a", dimensions: { width: 10, height: 20 }, resizing: false },
        { type: "select", id: "a", selected: true },
        { type: "remove", id: "b" },
        { type: "add", item: { id: "c", position: { x: 0, y: 0 }, data: {} } },
        { type: "replace", id: "d", item: { id: "d", position: { x: 0, y: 0 }, data: {} } },
      ]),
    ).toEqual([
      { type: "position", id: "a", position: { x: 1, y: 2 }, dragging: true },
      { type: "dimensions", id: "a", dimensions: { width: 10, height: 20 }, resizing: false },
      { type: "select", id: "a", selected: true },
      { type: "remove", id: "b" },
    ]);
  });
});
