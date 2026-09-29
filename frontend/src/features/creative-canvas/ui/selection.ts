/**
 * Selection is view state held on the nodes (`selected`), which React Flow
 * renders from. The ported domain reducers treat a select change as a non-edit
 * and leave node flags alone, so the adapter applies it here.
 */
import { applyNodeChanges, selectNode } from "../domain/graph";
import type { CanvasGraphState, NodeChange } from "../domain/types";

type SelectChange = Extract<NodeChange, { type: "select" }>;

export function applySelection(graph: CanvasGraphState, changes: readonly SelectChange[]): CanvasGraphState {
  if (changes.length === 0) return graph;
  const selected = new Map(changes.map((change) => [change.id, change.selected] as const));
  let changed = false;
  const nodes = graph.nodes.map((node) => {
    const next = selected.get(node.id);
    if (next === undefined || Boolean(node.selected) === next) return node;
    changed = true;
    return { ...node, selected: next };
  });
  if (!changed) return graph;
  const primary = [...selected].reverse().find(([, value]) => value)?.[0] ?? nodes.find((node) => node.selected)?.id ?? null;
  return selectNode({ ...graph, nodes }, primary);
}

/** Apply React Flow's node changes: the domain for edits, then the selection flags. */
export function applyFlowNodeChanges(graph: CanvasGraphState, changes: readonly NodeChange[]): CanvasGraphState {
  const selects = changes.filter((change): change is SelectChange => change.type === "select");
  const others = changes.filter((change) => change.type !== "select");
  const edited = others.length > 0 ? applyNodeChanges(graph, others) : graph;
  return applySelection(edited, selects);
}

/** Select `nodeId` alone, as a click does. */
export function selectOnly(graph: CanvasGraphState, nodeId: string): CanvasGraphState {
  return applySelection(
    graph,
    graph.nodes.flatMap((node): SelectChange[] =>
      node.id === nodeId
        ? [{ type: "select", id: node.id, selected: true }]
        : node.selected
          ? [{ type: "select", id: node.id, selected: false }]
          : [],
    ),
  );
}
