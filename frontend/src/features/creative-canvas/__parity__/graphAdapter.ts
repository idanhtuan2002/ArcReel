/**
 * Port side of the donor parity harness for graph and history behavior.
 *
 * `runGraphCase` replays one canonical fixture case against the pure port and
 * returns one observation after every operation. The donor side replays the
 * same cases against the DramaClaw store (tools/parity/dramaclaw/); the two
 * observation lists are compared field by field.
 */

import {
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
  redo,
  restoreHistory,
  selectNode,
  undo,
} from "../domain/graph";
import type { CanvasEdge, CanvasGraphState, CanvasNode, CanvasNodeType, MutationState, NodeChange } from "../domain/types";

export interface FixtureNode {
  id: string;
  type: CanvasNodeType;
  parentId?: string;
  x?: number;
  y?: number;
}

export interface FixtureEdge {
  id: string;
  source: string;
  target: string;
}

export type FixtureOp =
  | { op: "load"; nodes: FixtureNode[]; edges: FixtureEdge[] }
  | { op: "hydrate"; nodes: FixtureNode[]; edges: FixtureEdge[]; mutation: MutationState }
  | { op: "add"; node: FixtureNode }
  | { op: "addMany"; count: number; prefix: string }
  | { op: "connect"; source: string; target: string; id: string }
  | { op: "delete"; ids: string[] }
  | { op: "deleteEdge"; id: string }
  | { op: "clear" }
  | { op: "ack" }
  | { op: "select"; id: string | null }
  | { op: "undo" }
  | { op: "redo" }
  | { op: "undoMany"; count: number }
  | { op: "redoMany"; count: number }
  | { op: "changes"; changes: NodeChange[] }
  | { op: "restoreHistoryOf"; count: number; prefix: string };

export interface FixtureCase {
  id: string;
  behaviors: string[];
  ops: FixtureOp[];
}

export interface GraphObservation {
  op: string;
  nodes: { id: string; type: string; parentId: string | null; x: number; y: number }[];
  edges: { id: string; source: string; target: string; sourceHandle: string; targetHandle: string }[];
  past: number;
  future: number;
  selected: string | null;
  edits: number;
  source: string | null;
  pendingClear: boolean;
}

export function toNode(item: FixtureNode): CanvasNode {
  return {
    id: item.id,
    type: item.type,
    position: { x: item.x ?? 0, y: item.y ?? 0 },
    data: {},
    ...(item.parentId ? { parentId: item.parentId } : {}),
  };
}

function toEdge(item: FixtureEdge): CanvasEdge {
  return { id: item.id, source: item.source, target: item.target };
}

export function observe(op: string, state: CanvasGraphState): GraphObservation {
  return {
    op,
    nodes: state.nodes.map((node) => ({
      id: node.id,
      type: node.type,
      parentId: node.parentId ?? null,
      x: node.position.x,
      y: node.position.y,
    })),
    edges: state.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle ?? "source",
      targetHandle: edge.targetHandle ?? "target",
    })),
    past: state.history.past.length,
    future: state.history.future.length,
    selected: state.selectedNodeId,
    edits: state.userEditsSinceHydrate,
    source: state.lastMutationSource,
    pendingClear: state.pendingClearIntent,
  };
}

function apply(state: CanvasGraphState, op: FixtureOp): CanvasGraphState {
  switch (op.op) {
    case "load":
      return loadGraph(state, op.nodes.map(toNode), op.edges.map(toEdge));
    case "hydrate":
      return hydrateDraft(state, {
        nodes: op.nodes.map(toNode),
        edges: op.edges.map(toEdge),
        history: null,
        mutation: op.mutation,
      });
    case "add":
      return addNode(state, toNode(op.node));
    case "addMany": {
      let next = state;
      for (let index = 0; index < op.count; index += 1) {
        next = addNode(next, toNode({ id: `${op.prefix}${index}`, type: "note" }));
      }
      return next;
    }
    case "connect":
      return addEdge(state, { source: op.source, target: op.target }, op.id);
    case "delete":
      return deleteNodes(state, op.ids);
    case "deleteEdge":
      return deleteEdge(state, op.id);
    case "clear":
      return clearCanvas(state);
    case "ack":
      return acknowledgeClear(state);
    case "select":
      return selectNode(state, op.id);
    case "undo":
      return undo(state).state;
    case "redo":
      return redo(state).state;
    case "undoMany": {
      let next = state;
      for (let index = 0; index < op.count; index += 1) next = undo(next).state;
      return next;
    }
    case "redoMany": {
      let next = state;
      for (let index = 0; index < op.count; index += 1) next = redo(next).state;
      return next;
    }
    case "changes":
      return applyNodeChanges(state, op.changes);
    case "restoreHistoryOf": {
      const past = Array.from({ length: op.count }, (_, index) => ({
        nodes: [toNode({ id: `${op.prefix}${index}`, type: "note" })],
        edges: [],
      }));
      return restoreHistory(state, { past, future: [] });
    }
  }
}

export function runGraphCase(fixture: FixtureCase): GraphObservation[] {
  let state = createGraphState();
  const observations: GraphObservation[] = [];
  for (const op of fixture.ops) {
    state = apply(state, op);
    observations.push(observe(op.op, state));
  }
  return observations;
}
