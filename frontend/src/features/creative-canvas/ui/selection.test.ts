import { describe, expect, it } from "vitest";

import { addNode, createGraphState } from "../domain/graph";
import type { CanvasGraphState } from "../domain/types";
import { applyFlowNodeChanges, applySelection, selectOnly } from "./selection";

function graph(): CanvasGraphState {
  let state = createGraphState();
  for (const id of ["a", "b", "c"]) state = addNode(state, { id, type: "note", position: { x: 0, y: 0 }, data: {} });
  return state;
}

const selectedIds = (state: CanvasGraphState) => state.nodes.filter((node) => node.selected).map((node) => node.id);

describe("canvas selection", () => {
  it("sets the selected flags without counting an edit", () => {
    const before = graph();

    const after = applySelection(before, [
      { type: "select", id: "a", selected: true },
      { type: "select", id: "c", selected: true },
    ]);

    expect(selectedIds(after)).toEqual(["a", "c"]);
    expect(after.selectedNodeId).toBe("c");
    expect(after.userEditsSinceHydrate).toBe(before.userEditsSinceHydrate);
    expect(after.history).toBe(before.history);
  });

  it("returns the same state when nothing changes", () => {
    const state = graph();

    expect(applySelection(state, [{ type: "select", id: "a", selected: false }])).toBe(state);
  });

  it("selects one node alone", () => {
    const state = selectOnly(applySelection(graph(), [{ type: "select", id: "a", selected: true }]), "b");

    expect(selectedIds(state)).toEqual(["b"]);
    expect(state.selectedNodeId).toBe("b");
  });

  it("applies edits through the domain and selection on top", () => {
    const state = applyFlowNodeChanges(graph(), [
      { type: "select", id: "b", selected: true },
      { type: "remove", id: "a" },
    ]);

    expect(state.nodes.map((node) => node.id)).toEqual(["b", "c"]);
    expect(selectedIds(state)).toEqual(["b"]);
  });
});
