import { describe, expect, it } from "vitest";

import { toDomainChanges, toMeasurements } from "./CanvasBoard";

describe("React Flow node changes", () => {
  it("keeps the changes the domain handles and drops add and replace", () => {
    expect(
      toDomainChanges([
        { type: "position", id: "a", position: { x: 1, y: 2 }, dragging: true },
        { type: "dimensions", id: "a", dimensions: { width: 10, height: 20 }, resizing: false },
        { type: "dimensions", id: "m", dimensions: { width: 30, height: 40 } },
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

describe("React Flow measurements", () => {
  it("are the size changes that are neither a resize nor set attributes", () => {
    expect(
      toMeasurements([
        { type: "dimensions", id: "m", dimensions: { width: 30, height: 40 } },
        { type: "dimensions", id: "r", dimensions: { width: 10, height: 20 }, resizing: true },
        { type: "dimensions", id: "s", dimensions: { width: 10, height: 20 }, setAttributes: true },
        { type: "select", id: "a", selected: true },
      ]),
    ).toEqual([{ id: "m", width: 30, height: 40 }]);
  });
});
