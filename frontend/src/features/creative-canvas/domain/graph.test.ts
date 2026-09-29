import { describe, expect, it } from "vitest";

import {
  MAX_HISTORY_STEPS,
  acknowledgeClear,
  addEdge,
  addNode,
  applyNodeChanges,
  clearCanvas,
  createGraphState,
  deleteEdge,
  deleteNodes,
  hydrateDraft,
  loadGraph,
  normalizeGraph,
  redo,
  restoreHistory,
  selectNode,
  undo,
} from "./graph";
import type { CanvasEdge, CanvasNode } from "./types";

function node(id: string, overrides: Partial<CanvasNode> = {}): CanvasNode {
  return { id, type: "note", position: { x: 0, y: 0 }, data: {}, ...overrides };
}

function edge(id: string, source: string, target: string): CanvasEdge {
  return { id, source, target };
}

describe("normalizeGraph", () => {
  it("drops edges whose endpoints are missing and fills default handles and type", () => {
    const graph = normalizeGraph([node("a"), node("b")], [edge("e1", "a", "b"), edge("e2", "a", "missing")]);

    expect(graph.edges).toEqual([
      { id: "e1", source: "a", target: "b", sourceHandle: "source", targetHandle: "target", type: "disconnectableEdge" },
    ]);
  });

  it("keeps the first position of a duplicated id with the later value, and orders parents before children", () => {
    const graph = normalizeGraph(
      [node("child", { parentId: "g" }), node("g", { type: "group" }), node("child", { parentId: "g", data: { v: 2 } })],
      [],
    );

    expect(graph.nodes.map((item) => item.id)).toEqual(["g", "child"]);
    expect(graph.nodes[1].data).toEqual({ v: 2 });
  });

  it("detaches a child whose parent is missing", () => {
    const graph = normalizeGraph([node("orphan", { parentId: "gone", extent: "parent" })], []);

    expect(graph.nodes[0].parentId).toBeUndefined();
    expect(graph.nodes[0].extent).toBeUndefined();
  });
});

describe("history", () => {
  it("keeps at most MAX_HISTORY_STEPS past snapshots and drops the oldest", () => {
    let state = createGraphState();
    for (let index = 0; index < MAX_HISTORY_STEPS + 10; index += 1) {
      state = addNode(state, node(`n${index}`));
    }

    expect(MAX_HISTORY_STEPS).toBe(50);
    expect(state.history.past).toHaveLength(MAX_HISTORY_STEPS);
    expect(state.history.past[0].nodes).toHaveLength(10);
  });

  it("undo and redo restore snapshots and report whether anything changed", () => {
    let state = addNode(createGraphState(), node("a"));

    const undone = undo(state);
    expect(undone.changed).toBe(true);
    expect(undone.state.nodes).toEqual([]);
    expect(undone.state.history.future).toHaveLength(1);

    const redone = redo(undone.state);
    expect(redone.changed).toBe(true);
    expect(redone.state.nodes.map((item) => item.id)).toEqual(["a"]);

    state = createGraphState();
    expect(undo(state)).toEqual({ state, changed: false });
    expect(redo(state)).toEqual({ state, changed: false });
  });

  it("undo resolves a selection that no longer exists", () => {
    const state = selectNode(addNode(createGraphState(), node("a")), "a");

    expect(undo(state).state.selectedNodeId).toBeNull();
  });

  it("an undo that empties the canvas records delete_to_empty", () => {
    const state = addNode(createGraphState(), node("a"));

    expect(undo(state).state.lastMutationSource).toBe("delete_to_empty");
  });

  it("restoreHistory normalizes and bounds a stored history", () => {
    const snapshots = Array.from({ length: 60 }, (_, index) => ({ nodes: [node(`n${index}`)], edges: [] }));
    const state = restoreHistory(createGraphState(), { past: snapshots, future: [] });

    expect(state.history.past).toHaveLength(MAX_HISTORY_STEPS);
    expect(state.history.past[0].nodes[0].id).toBe("n10");
  });
});

describe("node changes", () => {
  it("auto-measurement does not push history; a finished resize does", () => {
    let state = addNode(createGraphState(), node("a"));
    state = applyNodeChanges(state, [{ type: "dimensions", id: "a", dimensions: { width: 320, height: 200 } }]);
    expect(state.history.past).toHaveLength(1);

    state = applyNodeChanges(state, [
      { type: "dimensions", id: "a", resizing: false, dimensions: { width: 400, height: 300 } },
    ]);
    expect(state.history.past).toHaveLength(2);
    expect(state.nodes[0].width).toBe(400);
  });

  it("a drag snapshots once at the first move and pushes one step at the end", () => {
    let state = addNode(createGraphState(), node("a"));
    state = applyNodeChanges(state, [{ type: "position", id: "a", position: { x: 5, y: 0 }, dragging: true }]);
    state = applyNodeChanges(state, [{ type: "position", id: "a", position: { x: 9, y: 0 }, dragging: true }]);
    state = applyNodeChanges(state, [{ type: "position", id: "a", position: { x: 9, y: 0 }, dragging: false }]);

    expect(state.history.past).toHaveLength(2);
    expect(state.history.past[1].nodes[0].position).toEqual({ x: 0, y: 0 });
    expect(state.nodes[0].position).toEqual({ x: 9, y: 0 });
  });

  it("selection changes are not edits", () => {
    const state = applyNodeChanges(addNode(createGraphState(), node("a")), [
      { type: "select", id: "a", selected: true },
    ]);

    expect(state.userEditsSinceHydrate).toBe(1);
    expect(state.history.past).toHaveLength(1);
  });
});

describe("delete and clear", () => {
  it("deleting a group removes its descendants and incident edges", () => {
    let state = loadGraph(
      createGraphState(),
      [node("g", { type: "group" }), node("c", { parentId: "g" }), node("x")],
      [edge("e", "c", "x")],
    );
    state = deleteNodes(state, ["g"]);

    expect(state.nodes.map((item) => item.id)).toEqual(["x"]);
    expect(state.edges).toEqual([]);
    expect(state.lastMutationSource).toBe("user_edit");
  });

  it("deleting the last node records delete_to_empty and clears the selection", () => {
    let state = selectNode(loadGraph(createGraphState(), [node("a")], []), "a");
    state = deleteNodes(state, ["a", "a", " "]);

    expect(state.nodes).toEqual([]);
    expect(state.selectedNodeId).toBeNull();
    expect(state.lastMutationSource).toBe("delete_to_empty");
  });

  it("deleting unknown ids is a no-op", () => {
    const state = loadGraph(createGraphState(), [node("a")], []);

    expect(deleteNodes(state, ["missing"])).toBe(state);
  });

  it("deleteEdge pushes history and ignores unknown ids", () => {
    const state = loadGraph(createGraphState(), [node("a"), node("b")], [edge("e", "a", "b")]);

    expect(deleteEdge(state, "missing")).toBe(state);
    const next = deleteEdge(state, "e");
    expect(next.edges).toEqual([]);
    expect(next.history.past).toHaveLength(1);
  });

  it("clear records manual_clear and a pending clear intent; acknowledge consumes the intent", () => {
    let state = loadGraph(createGraphState(), [node("a")], [], undefined);
    state = clearCanvas(state);

    expect(state.nodes).toEqual([]);
    expect(state.lastMutationSource).toBe("manual_clear");
    expect(state.pendingClearIntent).toBe(true);
    expect(acknowledgeClear(state).pendingClearIntent).toBe(false);
    expect(clearCanvas(createGraphState())).toEqual(createGraphState());
  });

  it("load resets the mutation state; hydrateDraft restores it", () => {
    const loaded = loadGraph(addNode(createGraphState(), node("a")), [node("b")], []);
    expect(loaded.userEditsSinceHydrate).toBe(0);
    expect(loaded.lastMutationSource).toBeNull();

    const hydrated = hydrateDraft(createGraphState(), {
      nodes: [node("a")],
      edges: [],
      history: null,
      mutation: { userEditsSinceHydrate: 3, lastMutationSource: "manual_clear", pendingClearIntent: true },
    });
    expect(hydrated.userEditsSinceHydrate).toBe(3);
    expect(hydrated.pendingClearIntent).toBe(true);
  });

  it("addEdge connects existing nodes once and records an edit", () => {
    const state = loadGraph(createGraphState(), [node("a"), node("b")], []);
    const connected = addEdge(state, { source: "a", target: "b" }, "e1");

    expect(connected.edges).toHaveLength(1);
    expect(addEdge(connected, { source: "a", target: "b" }, "e2")).toBe(connected);
    expect(addEdge(state, { source: "a", target: "missing" }, "e3")).toBe(state);
  });
});
