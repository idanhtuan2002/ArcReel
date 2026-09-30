/**
 * Pure graph, history and mutation-tracking reducers of the Creative Canvas.
 *
 * Ported from the DramaClaw canvas store (b299bfd9, `stores/canvasStore.ts`):
 * normalization, bounded undo/redo, drag/resize history, delete with
 * descendants, delete-to-empty and explicit clear. Donor-only concerns
 * (generation flags, projection keys, preset-managed nodes, the node-type
 * connection matrix) are not part of the ArcReel Canvas. Every function returns
 * a new state, or the same state object when nothing changed.
 */

import type {
  CanvasEdge,
  CanvasGraphState,
  CanvasNode,
  Connection,
  HistorySnapshot,
  HistoryState,
  MutationSource,
  MutationState,
  NodeChange,
} from "./types";

export const MAX_HISTORY_STEPS = 50;
const DEFAULT_EDGE_TYPE = "disconnectableEdge";

export function createGraphState(): CanvasGraphState {
  return {
    nodes: [],
    edges: [],
    selectedNodeId: null,
    history: { past: [], future: [] },
    dragSnapshot: null,
    userEditsSinceHydrate: 0,
    lastMutationSource: null,
    pendingClearIntent: false,
  };
}

// ─── normalization ─────────────────────────────────────────────────────────

function normalizeHandle(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  if (!trimmed || trimmed === "null" || trimmed === "undefined")
    return undefined;
  return trimmed;
}

/** A later node with the same id replaces the earlier one, at the earlier position. */
function dedupeById<T extends { id: string }>(items: readonly T[]): T[] {
  const indexById = new Map<string, number>();
  const result: T[] = [];
  for (const item of items) {
    const existing = indexById.get(item.id);
    if (existing === undefined) {
      indexById.set(item.id, result.length);
      result.push(item);
    } else {
      result[existing] = item;
    }
  }
  return result;
}

function detachMissingParents(nodes: readonly CanvasNode[]): CanvasNode[] {
  const ids = new Set(nodes.map((node) => node.id));
  return nodes.map((node) => {
    if (!node.parentId || ids.has(node.parentId)) return node;
    const { parentId: _parentId, extent: _extent, ...rest } = node;
    return rest;
  });
}

function sortParentsBeforeChildren(nodes: readonly CanvasNode[]): CanvasNode[] {
  const byId = new Map(nodes.map((node) => [node.id, node] as const));
  const visited = new Set<string>();
  const visiting = new Set<string>();
  const sorted: CanvasNode[] = [];
  const visit = (node: CanvasNode): void => {
    if (visited.has(node.id)) return;
    if (visiting.has(node.id)) {
      sorted.push(node);
      visited.add(node.id);
      return;
    }
    visiting.add(node.id);
    const parent = node.parentId ? byId.get(node.parentId) : undefined;
    if (parent) visit(parent);
    visiting.delete(node.id);
    if (!visited.has(node.id)) {
      sorted.push(node);
      visited.add(node.id);
    }
  };
  for (const node of nodes) visit(node);
  return sorted;
}

function normalizeNodes(nodes: readonly CanvasNode[]): CanvasNode[] {
  return sortParentsBeforeChildren(detachMissingParents(dedupeById(nodes)));
}

function normalizeEdges(
  edges: readonly CanvasEdge[],
  nodes: readonly CanvasNode[],
): CanvasEdge[] {
  const ids = new Set(nodes.map((node) => node.id));
  const normalized = edges
    .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
    .map((edge) => ({
      ...edge,
      type: edge.type ?? DEFAULT_EDGE_TYPE,
      sourceHandle: normalizeHandle(edge.sourceHandle) ?? "source",
      targetHandle: normalizeHandle(edge.targetHandle) ?? "target",
    }));
  return dedupeById(normalized);
}

export function normalizeGraph(
  nodes: readonly CanvasNode[],
  edges: readonly CanvasEdge[],
): { nodes: CanvasNode[]; edges: CanvasEdge[] } {
  const normalizedNodes = normalizeNodes(nodes);
  return {
    nodes: normalizedNodes,
    edges: normalizeEdges(edges, normalizedNodes),
  };
}

// ─── history ───────────────────────────────────────────────────────────────

function snapshot(
  state: Pick<CanvasGraphState, "nodes" | "edges">,
): HistorySnapshot {
  return { nodes: state.nodes, edges: state.edges };
}

/** Append a snapshot, skipping one identical to the last, and keep the newest MAX_HISTORY_STEPS. */
function pushSnapshot(
  snapshots: readonly HistorySnapshot[],
  next: HistorySnapshot,
): readonly HistorySnapshot[] {
  const last = snapshots[snapshots.length - 1];
  if (last && last.nodes === next.nodes && last.edges === next.edges)
    return snapshots;
  const result = [...snapshots, next];
  if (result.length > MAX_HISTORY_STEPS) result.shift();
  return result;
}

function normalizeHistory(history?: HistoryState | null): HistoryState {
  if (!history) return { past: [], future: [] };
  const normalize = (item: HistorySnapshot): HistorySnapshot =>
    normalizeGraph(item.nodes, item.edges);
  return {
    past: history.past.slice(-MAX_HISTORY_STEPS).map(normalize),
    future: history.future.slice(-MAX_HISTORY_STEPS).map(normalize),
  };
}

function isDeleteToEmpty(previousCount: number, nextCount: number): boolean {
  return previousCount > 0 && nextCount === 0;
}

function trackEdit(
  state: Pick<MutationState, "userEditsSinceHydrate">,
  source: MutationSource = "user_edit",
): Pick<MutationState, "userEditsSinceHydrate" | "lastMutationSource"> {
  return {
    userEditsSinceHydrate: state.userEditsSinceHydrate + 1,
    lastMutationSource: source,
  };
}

function resolveSelection(
  selected: string | null,
  nodes: readonly CanvasNode[],
): string | null {
  if (!selected) return null;
  return nodes.some((node) => node.id === selected) ? selected : null;
}

/** Commit an edit: push the pre-edit snapshot, clear redo, count the edit. */
export function commitEdit(
  state: CanvasGraphState,
  nodes: readonly CanvasNode[],
  edges: readonly CanvasEdge[],
  source: MutationSource = "user_edit",
): CanvasGraphState {
  return {
    ...state,
    nodes,
    edges,
    history: {
      past: pushSnapshot(state.history.past, snapshot(state)),
      future: [],
    },
    dragSnapshot: null,
    ...trackEdit(state, source),
  };
}

export function undo(state: CanvasGraphState): {
  state: CanvasGraphState;
  changed: boolean;
} {
  const target = state.history.past[state.history.past.length - 1];
  if (!target) return { state, changed: false };
  const source: MutationSource = isDeleteToEmpty(
    state.nodes.length,
    target.nodes.length,
  )
    ? "delete_to_empty"
    : "user_edit";
  return {
    changed: true,
    state: {
      ...state,
      nodes: target.nodes,
      edges: target.edges,
      selectedNodeId: resolveSelection(state.selectedNodeId, target.nodes),
      history: {
        past: state.history.past.slice(0, -1),
        future: pushSnapshot(state.history.future, snapshot(state)),
      },
      dragSnapshot: null,
      ...trackEdit(state, source),
    },
  };
}

export function redo(state: CanvasGraphState): {
  state: CanvasGraphState;
  changed: boolean;
} {
  const target = state.history.future[state.history.future.length - 1];
  if (!target) return { state, changed: false };
  const source: MutationSource = isDeleteToEmpty(
    state.nodes.length,
    target.nodes.length,
  )
    ? "delete_to_empty"
    : "user_edit";
  return {
    changed: true,
    state: {
      ...state,
      nodes: target.nodes,
      edges: target.edges,
      selectedNodeId: resolveSelection(state.selectedNodeId, target.nodes),
      history: {
        past: pushSnapshot(state.history.past, snapshot(state)),
        future: state.history.future.slice(0, -1),
      },
      dragSnapshot: null,
      ...trackEdit(state, source),
    },
  };
}

export function restoreHistory(
  state: CanvasGraphState,
  history: HistoryState,
): CanvasGraphState {
  return { ...state, history: normalizeHistory(history) };
}

// ─── load and hydrate ──────────────────────────────────────────────────────

/** Load server content: normalized, fresh mutation state, no selection. */
export function loadGraph(
  state: CanvasGraphState,
  nodes: readonly CanvasNode[],
  edges: readonly CanvasEdge[],
  history?: HistoryState | null,
): CanvasGraphState {
  const graph = normalizeGraph(nodes, edges);
  return {
    ...state,
    nodes: graph.nodes,
    edges: graph.edges,
    selectedNodeId: null,
    history: normalizeHistory(history),
    dragSnapshot: null,
    userEditsSinceHydrate: 0,
    lastMutationSource: null,
    pendingClearIntent: false,
  };
}

/** Restore a local draft, including its mutation state. */
export function hydrateDraft(
  state: CanvasGraphState,
  draft: {
    nodes: readonly CanvasNode[];
    edges: readonly CanvasEdge[];
    history: HistoryState | null;
    mutation: MutationState;
  },
): CanvasGraphState {
  const graph = normalizeGraph(draft.nodes, draft.edges);
  return {
    ...state,
    nodes: graph.nodes,
    edges: graph.edges,
    selectedNodeId: null,
    history: normalizeHistory(draft.history),
    dragSnapshot: null,
    userEditsSinceHydrate: draft.mutation.userEditsSinceHydrate,
    lastMutationSource: draft.mutation.lastMutationSource,
    pendingClearIntent: draft.mutation.pendingClearIntent,
  };
}

// ─── edits ─────────────────────────────────────────────────────────────────

export function addNode(
  state: CanvasGraphState,
  node: CanvasNode,
): CanvasGraphState {
  return commitEdit(state, [...state.nodes, node], state.edges);
}

function connectionExists(
  edges: readonly CanvasEdge[],
  edge: CanvasEdge,
): boolean {
  return edges.some(
    (item) =>
      item.source === edge.source &&
      item.target === edge.target &&
      (item.sourceHandle ?? "source") === (edge.sourceHandle ?? "source") &&
      (item.targetHandle ?? "target") === (edge.targetHandle ?? "target"),
  );
}

export function addEdge(
  state: CanvasGraphState,
  connection: Connection,
  edgeId: string,
): CanvasGraphState {
  const ids = new Set(state.nodes.map((node) => node.id));
  if (!ids.has(connection.source) || !ids.has(connection.target)) return state;
  const edge: CanvasEdge = {
    id: edgeId,
    source: connection.source,
    target: connection.target,
    sourceHandle: normalizeHandle(connection.sourceHandle) ?? "source",
    targetHandle: normalizeHandle(connection.targetHandle) ?? "target",
    type: DEFAULT_EDGE_TYPE,
  };
  if (connectionExists(state.edges, edge)) return state;
  return commitEdit(state, state.nodes, [...state.edges, edge]);
}

function collectWithDescendants(
  nodes: readonly CanvasNode[],
  seeds: readonly string[],
): Set<string> {
  const result = new Set(seeds);
  let changed = true;
  while (changed) {
    changed = false;
    for (const node of nodes) {
      if (node.parentId && !result.has(node.id) && result.has(node.parentId)) {
        result.add(node.id);
        changed = true;
      }
    }
  }
  return result;
}

export function deleteNodes(
  state: CanvasGraphState,
  nodeIds: readonly string[],
): CanvasGraphState {
  const unique = Array.from(
    new Set(nodeIds.filter((id) => id.trim().length > 0)),
  );
  const existing = unique.filter((id) =>
    state.nodes.some((node) => node.id === id),
  );
  if (existing.length === 0) return state;
  const doomed = collectWithDescendants(state.nodes, existing);
  const nodes = state.nodes.filter((node) => !doomed.has(node.id));
  const edges = state.edges.filter(
    (edge) => !doomed.has(edge.source) && !doomed.has(edge.target),
  );
  const source: MutationSource = isDeleteToEmpty(
    state.nodes.length,
    nodes.length,
  )
    ? "delete_to_empty"
    : "user_edit";
  return {
    ...commitEdit(state, nodes, edges, source),
    selectedNodeId:
      state.selectedNodeId && doomed.has(state.selectedNodeId)
        ? null
        : state.selectedNodeId,
  };
}

export function deleteEdge(
  state: CanvasGraphState,
  edgeId: string,
): CanvasGraphState {
  if (!state.edges.some((edge) => edge.id === edgeId)) return state;
  return commitEdit(
    state,
    state.nodes,
    state.edges.filter((edge) => edge.id !== edgeId),
  );
}

export function clearCanvas(state: CanvasGraphState): CanvasGraphState {
  if (state.nodes.length === 0 && state.edges.length === 0) return state;
  return {
    ...commitEdit(state, [], [], "manual_clear"),
    selectedNodeId: null,
    pendingClearIntent: true,
  };
}

export function acknowledgeClear(state: CanvasGraphState): CanvasGraphState {
  return state.pendingClearIntent
    ? { ...state, pendingClearIntent: false }
    : state;
}

export function selectNode(
  state: CanvasGraphState,
  nodeId: string | null,
): CanvasGraphState {
  return state.selectedNodeId === nodeId
    ? state
    : { ...state, selectedNodeId: nodeId };
}

// ─── node changes (drag, resize, measure, select, remove) ──────────────────

function applyChangesToNodes(
  nodes: readonly CanvasNode[],
  changes: readonly NodeChange[],
): CanvasNode[] {
  const removed = new Set(
    changes
      .filter((change) => change.type === "remove")
      .map((change) => change.id),
  );
  return nodes
    .filter((node) => !removed.has(node.id))
    .map((node) => {
      let next = node;
      for (const change of changes) {
        if (change.id !== node.id) continue;
        if (change.type === "position" && change.position) {
          next = {
            ...next,
            position: { x: change.position.x, y: change.position.y },
          };
        } else if (change.type === "dimensions" && change.dimensions) {
          next = {
            ...next,
            width: change.dimensions.width,
            height: change.dimensions.height,
          };
        }
      }
      return next;
    });
}

/**
 * Apply view changes from the graph adapter. Auto-measurement and selection are
 * not edits. A drag or resize snapshots once at its first move and pushes one
 * history step when it ends; any other meaningful change pushes immediately.
 */
export function applyNodeChanges(
  state: CanvasGraphState,
  changes: readonly NodeChange[],
): CanvasGraphState {
  const nodes = applyChangesToNodes(state.nodes, changes);
  const meaningful = changes.some(
    (change) => change.type !== "select" && change.type !== "dimensions",
  );
  const dragMove = changes.some(
    (change) => change.type === "position" && Boolean(change.dragging),
  );
  const dragEnd = changes.some(
    (change) => change.type === "position" && change.dragging === false,
  );
  const resizeMove = changes.some(
    (change) => change.type === "dimensions" && Boolean(change.resizing),
  );
  const resizeEnd = changes.some(
    (change) => change.type === "dimensions" && change.resizing === false,
  );
  const interactionMove = dragMove || resizeMove;
  const interactionEnd = dragEnd || resizeEnd;

  let history = state.history;
  let dragSnapshot = state.dragSnapshot;
  let edited = false;
  if (interactionMove && !dragSnapshot) dragSnapshot = snapshot(state);
  if (interactionEnd) {
    history = {
      past: pushSnapshot(state.history.past, dragSnapshot ?? snapshot(state)),
      future: [],
    };
    dragSnapshot = null;
    edited = true;
  } else if (meaningful && !interactionMove) {
    history = {
      past: pushSnapshot(state.history.past, snapshot(state)),
      future: [],
    };
    dragSnapshot = null;
    edited = true;
  }
  const source: MutationSource = isDeleteToEmpty(
    state.nodes.length,
    nodes.length,
  )
    ? "delete_to_empty"
    : "user_edit";
  return {
    ...state,
    nodes,
    selectedNodeId: resolveSelection(state.selectedNodeId, nodes),
    history,
    dragSnapshot,
    ...(edited ? trackEdit(state, source) : {}),
  };
}
