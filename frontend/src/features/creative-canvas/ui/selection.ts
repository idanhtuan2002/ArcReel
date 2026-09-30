/**
 * View state React Flow renders from and the domain does not own: selection
 * (`selected`) and auto-measured size (`measured`). The ported domain reducers
 * treat both as non-edits and leave these fields alone, so the adapter applies
 * them here, as React Flow's own `applyNodeChanges` does: a measurement sets
 * `measured`, and only a resize writes `width` and `height` through the domain.
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

export interface Measurement {
  id: string;
  width: number;
  height: number;
}

/** Record React Flow's auto-measured sizes; visible-only rendering needs them. Not an edit. */
export function applyMeasurements(graph: CanvasGraphState, measurements: readonly Measurement[]): CanvasGraphState {
  if (measurements.length === 0) return graph;
  const byId = new Map(measurements.map((item) => [item.id, item] as const));
  let changed = false;
  const nodes = graph.nodes.map((node) => {
    const next = byId.get(node.id);
    if (!next || (node.measured?.width === next.width && node.measured.height === next.height)) return node;
    changed = true;
    return { ...node, measured: { width: next.width, height: next.height } };
  });
  return changed ? { ...graph, nodes } : graph;
}
