/**
 * Group, storyboard-group and sibling-duplicate reducers of the Creative Canvas.
 *
 * Ported from DramaClaw b299bfd9 (`stores/canvasStore.ts`: groupNodes,
 * ungroupNode, fitGroupToChildren, arrangeGroupChildren, mergeStoryboardGroup,
 * setStoryboardGroupConfig, reorderStoryboardMember, addStoryboardMembers,
 * convertStoryboardGroupToPlain, duplicateNodeAsSibling, duplicateNodesAsSiblings).
 * Donor-only concerns are not part of the ArcReel Canvas: protected projection
 * groups, auto-grouping of generated spawns, and the style-node edge rule.
 *
 * New ids and localized names come from the caller (`GroupDeps`), so the
 * reducers stay pure and deterministic.
 */

import {
  isGroupNode,
  isStoryboardGroupNode,
  nodeSize,
  resolveAbsolutePosition,
} from "./geometry";
import { commitEdit } from "./graph";
import {
  DEFAULT_STORYBOARD_ASPECT,
  computeStoryboardBoardLayout,
  computeStoryboardCell,
  computeStoryboardGridLayout,
  resolveStoryboardCols,
} from "./storyboardLayout";
import type {
  CanvasEdge,
  CanvasGraphState,
  CanvasNode,
  CanvasNodeType,
  XY,
} from "./types";

export interface GroupNaming {
  /** Default name of the n-th plain group. */
  group(index: number): string;
  /** Default name of the n-th storyboard group. */
  storyboard(index: number): string;
  /** Name of a copy of `name`. */
  copy(name: string): string;
  /** Default name of a storyboard frame. */
  frame(): string;
}

export interface GroupDeps {
  newId(): string;
  naming: GroupNaming;
}

const GROUP_SIDE_PADDING = 20;
const GROUP_TOP_PADDING = 34;
const GROUP_BOTTOM_PADDING = 20;
const MIN_GROUP_WIDTH = 220;
const MIN_GROUP_HEIGHT = 140;
const ARRANGE_GAP = 32;
const SIBLING_GAP = 24;
const UNMEASURED_SIBLING_HEIGHT = 360;
const STORYBOARD_DRAG_HANDLE = ".storyboard-group-drag-handle";

type NodeData = Record<string, unknown>;

function createNode(
  id: string,
  type: CanvasNodeType,
  position: XY,
  data: NodeData,
): CanvasNode {
  return { id, type, position, data };
}

function uniqueExistingIds(
  state: CanvasGraphState,
  nodeIds: readonly string[],
): string[] {
  const ids = new Set(state.nodes.map((node) => node.id));
  return Array.from(
    new Set(nodeIds.filter((id) => id.trim().length > 0)),
  ).filter((id) => ids.has(id));
}

/** Drop members whose ancestor is also selected: the ancestor carries them. */
function topLevelMembers(
  ids: readonly string[],
  byId: ReadonlyMap<string, CanvasNode>,
): string[] {
  const selected = new Set(ids);
  return ids.filter((id) => {
    let parentId = byId.get(id)?.parentId;
    const visited = new Set<string>();
    while (parentId && !visited.has(parentId)) {
      if (selected.has(parentId)) return false;
      visited.add(parentId);
      parentId = byId.get(parentId)?.parentId;
    }
    return true;
  });
}

/** Place `group` just before the first member, keep everything else in order. */
function insertBeforeFirstMember(
  nodes: readonly CanvasNode[],
  group: CanvasNode,
  memberIds: ReadonlySet<string>,
  updated: ReadonlyMap<string, CanvasNode>,
  deselectOthers: "always" | "if-selected",
): CanvasNode[] {
  const firstIndex = nodes.findIndex((node) => memberIds.has(node.id));
  const next: CanvasNode[] = [];
  nodes.forEach((node, index) => {
    if (index === firstIndex) next.push(group);
    const member = updated.get(node.id);
    if (member) next.push(member);
    else if (deselectOthers === "always" || node.selected)
      next.push({ ...node, selected: false });
    else next.push(node);
  });
  if (firstIndex === -1) next.push(group);
  return next;
}

// ─── plain groups ──────────────────────────────────────────────────────────

/** Wrap at least two top-level members in a new group sized to their bounds. */
export function groupNodes(
  state: CanvasGraphState,
  nodeIds: readonly string[],
  deps: GroupDeps,
  options: { label?: string; extraPadding?: number } = {},
): { state: CanvasGraphState; groupId: string | null } {
  const existing = uniqueExistingIds(state, nodeIds);
  if (existing.length < 2) return { state, groupId: null };
  const byId = new Map(state.nodes.map((node) => [node.id, node] as const));
  const memberIds = topLevelMembers(existing, byId);
  if (memberIds.length < 2) return { state, groupId: null };
  const members = memberIds.map((id) => byId.get(id) as CanvasNode);

  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const node of members) {
    const absolute = resolveAbsolutePosition(node, byId);
    const size = nodeSize(node);
    minX = Math.min(minX, absolute.x);
    minY = Math.min(minY, absolute.y);
    maxX = Math.max(maxX, absolute.x + size.width);
    maxY = Math.max(maxY, absolute.y + size.height);
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY))
    return { state, groupId: null };

  const extra = Math.max(0, options.extraPadding ?? 0);
  const side = GROUP_SIDE_PADDING + extra;
  const top = GROUP_TOP_PADDING + extra;
  const bottom = GROUP_BOTTOM_PADDING + extra;
  const groupX = Math.round(minX - side);
  const groupY = Math.round(minY - top);
  const width = Math.round(Math.max(MIN_GROUP_WIDTH, maxX - minX + side * 2));
  const height = Math.round(
    Math.max(MIN_GROUP_HEIGHT, maxY - minY + top + bottom),
  );
  const existingGroups = state.nodes.filter(
    (node) => node.type === "group",
  ).length;
  const name = options.label?.trim() || deps.naming.group(existingGroups + 1);
  const group: CanvasNode = {
    ...createNode(
      deps.newId(),
      "group",
      { x: groupX, y: groupY },
      { label: name, displayName: name },
    ),
    width,
    height,
    style: { width, height },
    selected: true,
  };

  const updated = new Map<string, CanvasNode>();
  for (const node of members) {
    const absolute = resolveAbsolutePosition(node, byId);
    // Plain group members are not clamped to the frame; the group grows to them.
    const { extent: _extent, ...rest } = node;
    updated.set(node.id, {
      ...rest,
      parentId: group.id,
      position: {
        x: Math.round(absolute.x - groupX),
        y: Math.round(absolute.y - groupY),
      },
      selected: false,
    });
  }
  const nodes = insertBeforeFirstMember(
    state.nodes,
    group,
    new Set(memberIds),
    updated,
    "always",
  );
  return {
    state: {
      ...commitEdit(state, nodes, state.edges),
      selectedNodeId: group.id,
    },
    groupId: group.id,
  };
}

/** Restore the storyboard edge rewiring: re-anchor edges onto members and reveal internal ones. */
function restoreStoryboardEdges(
  edges: readonly CanvasEdge[],
  groupId: string,
  childIds: ReadonlySet<string>,
): CanvasEdge[] {
  return edges.map((edge) => {
    let next = edge;
    const sourceData = next.data;
    if (
      next.source === groupId &&
      typeof sourceData?.__sbOrigSource === "string"
    ) {
      const { __sbOrigSource, ...rest } = sourceData;
      next = { ...next, source: __sbOrigSource, data: rest };
    }
    const targetData = next.data;
    if (
      next.target === groupId &&
      typeof targetData?.__sbOrigTarget === "string"
    ) {
      const { __sbOrigTarget, ...rest } = targetData;
      next = { ...next, target: __sbOrigTarget, data: rest };
    }
    if (
      (childIds.has(next.source) || childIds.has(next.target)) &&
      next.hidden
    ) {
      next = { ...next, hidden: false };
    }
    return next;
  });
}

/** Remove a group, keeping its children at their absolute positions. */
export function ungroupNode(
  state: CanvasGraphState,
  groupId: string,
): { state: CanvasGraphState; changed: boolean } {
  const group = state.nodes.find(
    (node) => node.id === groupId && node.type === "group",
  );
  if (!group) return { state, changed: false };
  const children = state.nodes.filter((node) => node.parentId === groupId);
  if (children.length === 0) return { state, changed: false };
  const byId = new Map(state.nodes.map((node) => [node.id, node] as const));
  const nodes = state.nodes
    .filter((node) => node.id !== groupId)
    .map((node) => {
      if (node.parentId !== groupId) return node;
      const absolute = resolveAbsolutePosition(node, byId);
      const { parentId: _parentId, extent: _extent, ...rest } = node;
      return {
        ...rest,
        hidden: false,
        position: { x: Math.round(absolute.x), y: Math.round(absolute.y) },
        selected: false,
      };
    });
  const childIds = new Set(children.map((child) => child.id));
  const edges = restoreStoryboardEdges(state.edges, groupId, childIds).filter(
    (edge) => edge.source !== groupId && edge.target !== groupId,
  );
  const next = commitEdit(state, nodes, edges);
  return {
    changed: true,
    state: {
      ...next,
      selectedNodeId:
        state.selectedNodeId === groupId ? null : state.selectedNodeId,
    },
  };
}

function groupExtent(group: CanvasNode): { width: number; height: number } {
  return {
    width: Math.max(
      typeof group.style?.width === "number" ? group.style.width : 0,
      typeof group.width === "number" ? group.width : 0,
    ),
    height: Math.max(
      typeof group.style?.height === "number" ? group.style.height : 0,
      typeof group.height === "number" ? group.height : 0,
    ),
  };
}

/**
 * Grow a plain group to contain its children, pushing them inward when they
 * spill past the top/left edge. Grow-only, so a manual enlarge is kept. A pure
 * layout correction: no history step and no edit count.
 */
export function fitGroupToChildren(
  state: CanvasGraphState,
  groupId: string,
): CanvasGraphState {
  const group = state.nodes.find((node) => node.id === groupId);
  if (!isGroupNode(group) || isStoryboardGroupNode(group)) return state;
  const children = state.nodes.filter((node) => node.parentId === groupId);
  if (children.length === 0) return state;
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const child of children) {
    const size = nodeSize(child);
    minX = Math.min(minX, child.position.x);
    minY = Math.min(minY, child.position.y);
    maxX = Math.max(maxX, child.position.x + size.width);
    maxY = Math.max(maxY, child.position.y + size.height);
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY)) return state;
  const shiftX = Math.max(0, Math.round(GROUP_SIDE_PADDING - minX));
  const shiftY = Math.max(0, Math.round(GROUP_TOP_PADDING - minY));
  const current = groupExtent(group);
  const width = Math.max(
    current.width,
    Math.round(maxX + shiftX + GROUP_SIDE_PADDING),
  );
  const height = Math.max(
    current.height,
    Math.round(maxY + shiftY + GROUP_SIDE_PADDING),
  );
  if (
    shiftX === 0 &&
    shiftY === 0 &&
    width === current.width &&
    height === current.height
  )
    return state;
  const childIds = new Set(children.map((child) => child.id));
  const nodes = state.nodes.map((node) => {
    if (node.id === groupId) {
      return {
        ...node,
        position: { x: node.position.x - shiftX, y: node.position.y - shiftY },
        width,
        height,
        style: { ...node.style, width, height },
      };
    }
    if ((shiftX !== 0 || shiftY !== 0) && childIds.has(node.id)) {
      return {
        ...node,
        position: { x: node.position.x + shiftX, y: node.position.y + shiftY },
      };
    }
    return node;
  });
  return { ...state, nodes };
}

export type ArrangeMode = "horizontal" | "vertical" | "grid";

/** Lay the children of a plain group out in a row, a column or a near-square grid, then fit the group. */
export function arrangeGroupChildren(
  state: CanvasGraphState,
  groupId: string,
  mode: ArrangeMode,
): CanvasGraphState {
  const group = state.nodes.find((node) => node.id === groupId);
  if (!isGroupNode(group) || isStoryboardGroupNode(group)) return state;
  const children = state.nodes.filter((node) => node.parentId === groupId);
  if (children.length < 2) return state;
  const ordered = children
    .map((node) => ({ node, size: nodeSize(node) }))
    .sort(
      (a, b) =>
        a.node.position.y - b.node.position.y ||
        a.node.position.x - b.node.position.x,
    );
  const targets = new Map<string, XY>();
  if (mode === "horizontal") {
    let cursor = GROUP_SIDE_PADDING;
    for (const item of ordered) {
      targets.set(item.node.id, { x: cursor, y: GROUP_TOP_PADDING });
      cursor += item.size.width + ARRANGE_GAP;
    }
  } else if (mode === "vertical") {
    let cursor = GROUP_TOP_PADDING;
    for (const item of ordered) {
      targets.set(item.node.id, { x: GROUP_SIDE_PADDING, y: cursor });
      cursor += item.size.height + ARRANGE_GAP;
    }
  } else {
    const cols = Math.ceil(Math.sqrt(ordered.length));
    const cellWidth =
      Math.max(...ordered.map((item) => item.size.width)) + ARRANGE_GAP;
    const cellHeight =
      Math.max(...ordered.map((item) => item.size.height)) + ARRANGE_GAP;
    ordered.forEach((item, index) => {
      targets.set(item.node.id, {
        x: GROUP_SIDE_PADDING + (index % cols) * cellWidth,
        y: GROUP_TOP_PADDING + Math.floor(index / cols) * cellHeight,
      });
    });
  }
  let maxX = 0;
  let maxY = 0;
  for (const item of ordered) {
    const position = targets.get(item.node.id) as XY;
    maxX = Math.max(maxX, position.x + item.size.width);
    maxY = Math.max(maxY, position.y + item.size.height);
  }
  const width = Math.round(maxX + GROUP_SIDE_PADDING);
  const height = Math.round(maxY + GROUP_SIDE_PADDING);
  const nodes = state.nodes.map((node) => {
    if (node.id === groupId)
      return {
        ...node,
        width,
        height,
        style: { ...node.style, width, height },
      };
    const position = targets.get(node.id);
    return position ? { ...node, position } : node;
  });
  return commitEdit(state, nodes, state.edges);
}

// ─── storyboard groups ─────────────────────────────────────────────────────

/**
 * Merge at least two top-level members into a storyboard group. Members become
 * hidden thumbnails laid out in reading order on a full-size grid (so ungroup
 * spreads them cleanly); the group box follows the compact thumbnail board.
 * Edges between members are hidden; edges to outside nodes are re-anchored on
 * the group, remembering the member so ungroup/convert can restore them.
 */
export function mergeStoryboardGroup(
  state: CanvasGraphState,
  nodeIds: readonly string[],
  deps: GroupDeps,
): { state: CanvasGraphState; groupId: string | null } {
  const existing = uniqueExistingIds(state, nodeIds);
  if (existing.length < 2) return { state, groupId: null };
  const byId = new Map(state.nodes.map((node) => [node.id, node] as const));
  const memberIds = topLevelMembers(existing, byId);
  if (memberIds.length < 2) return { state, groupId: null };
  const ordered = memberIds
    .map((id) => byId.get(id) as CanvasNode)
    .sort((a, b) => {
      const pa = resolveAbsolutePosition(a, byId);
      const pb = resolveAbsolutePosition(b, byId);
      return pa.y - pb.y || pa.x - pb.x;
    });
  const baseWidth = Math.max(...ordered.map((node) => nodeSize(node).width));
  const baseHeight = Math.max(...ordered.map((node) => nodeSize(node).height));
  const aspectKey = DEFAULT_STORYBOARD_ASPECT;
  const cols = resolveStoryboardCols(ordered.length);
  const cell = computeStoryboardCell(baseWidth, baseHeight, aspectKey);
  const memberLayout = computeStoryboardGridLayout({
    count: ordered.length,
    cols,
    cellWidth: cell.cellWidth,
    cellHeight: cell.cellHeight,
  });
  const board = computeStoryboardBoardLayout({
    count: ordered.length,
    cols,
    aspectKey,
  });
  let anchorX = Number.POSITIVE_INFINITY;
  let anchorY = Number.POSITIVE_INFINITY;
  for (const node of ordered) {
    const absolute = resolveAbsolutePosition(node, byId);
    anchorX = Math.min(anchorX, absolute.x);
    anchorY = Math.min(anchorY, absolute.y);
  }
  const groupX = Math.round(Number.isFinite(anchorX) ? anchorX : 0);
  const groupY = Math.round(Number.isFinite(anchorY) ? anchorY : 0);
  const existingStoryboards = state.nodes.filter((node) =>
    isStoryboardGroupNode(node),
  ).length;
  const name = deps.naming.storyboard(existingStoryboards + 1);
  const group: CanvasNode = {
    ...createNode(
      deps.newId(),
      "group",
      { x: groupX, y: groupY },
      {
        label: name,
        displayName: name,
        storyboardGroup: true,
        storyboardAspect: aspectKey,
        storyboardCols: board.cols,
        storyboardShowIndex: false,
        storyboardBaseWidth: baseWidth,
        storyboardBaseHeight: baseHeight,
      },
    ),
    style: { width: board.groupWidth, height: board.groupHeight },
    dragHandle: STORYBOARD_DRAG_HANDLE,
    selected: true,
  };
  const memberSet = new Set(memberIds);
  const updated = new Map<string, CanvasNode>();
  ordered.forEach((node, index) => {
    const slot = memberLayout.cells[index];
    updated.set(node.id, {
      ...node,
      parentId: group.id,
      hidden: true,
      position: { x: slot.x, y: slot.y },
      selected: false,
    });
  });
  const nodes = insertBeforeFirstMember(
    state.nodes,
    group,
    memberSet,
    updated,
    "if-selected",
  );
  const edges = state.edges.map((edge) => {
    const fromMember = memberSet.has(edge.source);
    const toMember = memberSet.has(edge.target);
    if (fromMember && toMember) return { ...edge, hidden: true };
    if (fromMember)
      return {
        ...edge,
        source: group.id,
        data: { ...edge.data, __sbOrigSource: edge.source },
      };
    if (toMember)
      return {
        ...edge,
        target: group.id,
        data: { ...edge.data, __sbOrigTarget: edge.target },
      };
    return edge;
  });
  return {
    state: { ...commitEdit(state, nodes, edges), selectedNodeId: group.id },
    groupId: group.id,
  };
}

export function membersInReadingOrder(
  nodes: readonly CanvasNode[],
  groupId: string,
): CanvasNode[] {
  return nodes
    .filter((node) => node.parentId === groupId)
    .sort((a, b) => a.position.y - b.position.y || a.position.x - b.position.x);
}

function numberOr(value: unknown, fallback: number): number {
  return typeof value === "number" ? value : fallback;
}

/** Change a storyboard group's aspect, column count or index display; the board box follows. */
export function setStoryboardGroupConfig(
  state: CanvasGraphState,
  groupId: string,
  config: { aspectKey?: string; cols?: number; showIndex?: boolean },
): CanvasGraphState {
  const group = state.nodes.find((node) => node.id === groupId);
  if (!isStoryboardGroupNode(group)) return state;
  const aspectKey =
    config.aspectKey ??
    (group.data.storyboardAspect as string | undefined) ??
    DEFAULT_STORYBOARD_ASPECT;
  const showIndex =
    typeof config.showIndex === "boolean"
      ? config.showIndex
      : group.data.storyboardShowIndex === true;
  const count = state.nodes.filter((node) => node.parentId === groupId).length;
  const cols = resolveStoryboardCols(
    count,
    config.cols ?? (group.data.storyboardCols as number | undefined),
  );
  const board = computeStoryboardBoardLayout({ count, cols, aspectKey });
  const nodes = state.nodes.map((node) =>
    node.id === groupId
      ? {
          ...node,
          width: board.groupWidth,
          height: board.groupHeight,
          style: {
            ...node.style,
            width: board.groupWidth,
            height: board.groupHeight,
          },
          data: {
            ...node.data,
            storyboardAspect: aspectKey,
            storyboardCols: board.cols,
            storyboardShowIndex: showIndex,
          },
        }
      : node,
  );
  return commitEdit(state, nodes, state.edges);
}

function storyboardBase(
  group: CanvasNode,
  members: readonly CanvasNode[],
): { width: number; height: number } {
  return {
    width: numberOr(
      group.data.storyboardBaseWidth,
      members.length > 0
        ? Math.max(...members.map((node) => nodeSize(node).width))
        : 320,
    ),
    height: numberOr(
      group.data.storyboardBaseHeight,
      members.length > 0
        ? Math.max(...members.map((node) => nodeSize(node).height))
        : 200,
    ),
  };
}

/** Move a storyboard member from one reading-order index to another. */
export function reorderStoryboardMember(
  state: CanvasGraphState,
  groupId: string,
  fromIndex: number,
  toIndex: number,
): CanvasGraphState {
  const group = state.nodes.find((node) => node.id === groupId);
  if (!isStoryboardGroupNode(group)) return state;
  const members = membersInReadingOrder(state.nodes, groupId);
  if (
    fromIndex < 0 ||
    fromIndex >= members.length ||
    toIndex < 0 ||
    toIndex >= members.length ||
    fromIndex === toIndex
  ) {
    return state;
  }
  const reordered = [...members];
  const [moved] = reordered.splice(fromIndex, 1);
  reordered.splice(toIndex, 0, moved);
  const base = storyboardBase(group, members);
  const cols = resolveStoryboardCols(
    reordered.length,
    group.data.storyboardCols as number | undefined,
  );
  const cell = computeStoryboardCell(
    base.width,
    base.height,
    (group.data.storyboardAspect as string | undefined) ??
      DEFAULT_STORYBOARD_ASPECT,
  );
  const layout = computeStoryboardGridLayout({
    count: reordered.length,
    cols,
    cellWidth: cell.cellWidth,
    cellHeight: cell.cellHeight,
  });
  const positions = new Map<string, XY>();
  reordered.forEach((node, index) => {
    const slot = layout.cells[index];
    if (slot) positions.set(node.id, { x: slot.x, y: slot.y });
  });
  const nodes = state.nodes.map((node) => {
    const position = positions.get(node.id);
    return position ? { ...node, position } : node;
  });
  return commitEdit(state, nodes, state.edges);
}

/** Append frame members referencing existing assets to a storyboard group and re-lay the grid. */
export function addStoryboardMembers(
  state: CanvasGraphState,
  groupId: string,
  frames: readonly { assetRef: string; displayName?: string }[],
  deps: GroupDeps,
): CanvasGraphState {
  const valid = frames.filter((frame) => frame.assetRef.trim().length > 0);
  if (valid.length === 0) return state;
  const group = state.nodes.find((node) => node.id === groupId);
  if (!isStoryboardGroupNode(group)) return state;
  const existing = membersInReadingOrder(state.nodes, groupId);
  const base = storyboardBase(group, existing);
  const aspectKey =
    (group.data.storyboardAspect as string | undefined) ??
    DEFAULT_STORYBOARD_ASPECT;
  const width = Math.round(base.width);
  const height = Math.round(base.height);
  const created: CanvasNode[] = valid.map((frame) => ({
    ...createNode(
      deps.newId(),
      "frame",
      { x: 0, y: 0 },
      {
        assetRef: frame.assetRef,
        displayName: frame.displayName ?? deps.naming.frame(),
      },
    ),
    parentId: groupId,
    hidden: true,
    selected: false,
    width,
    height,
    style: { width, height },
  }));
  const all = [...existing, ...created];
  const cols = resolveStoryboardCols(
    all.length,
    group.data.storyboardCols as number | undefined,
  );
  const cell = computeStoryboardCell(base.width, base.height, aspectKey);
  const layout = computeStoryboardGridLayout({
    count: all.length,
    cols,
    cellWidth: cell.cellWidth,
    cellHeight: cell.cellHeight,
  });
  const board = computeStoryboardBoardLayout({
    count: all.length,
    cols,
    aspectKey,
  });
  const positions = new Map<string, XY>();
  all.forEach((node, index) => {
    const slot = layout.cells[index];
    if (slot) positions.set(node.id, { x: slot.x, y: slot.y });
  });
  const nodes = [
    ...state.nodes.map((node) => {
      if (node.id === groupId) {
        return {
          ...node,
          width: board.groupWidth,
          height: board.groupHeight,
          style: {
            ...node.style,
            width: board.groupWidth,
            height: board.groupHeight,
          },
          data: { ...node.data, storyboardCols: board.cols },
        };
      }
      const position = positions.get(node.id);
      return position ? { ...node, position } : node;
    }),
    ...created.map((node) => ({
      ...node,
      position: positions.get(node.id) ?? node.position,
    })),
  ];
  return commitEdit(state, nodes, state.edges);
}

/** Turn a storyboard group back into a plain group: reveal members, wrap them, restore edges. */
export function convertStoryboardGroupToPlain(
  state: CanvasGraphState,
  groupId: string,
): CanvasGraphState {
  const group = state.nodes.find((node) => node.id === groupId);
  if (!isStoryboardGroupNode(group)) return state;
  const children = state.nodes.filter((node) => node.parentId === groupId);
  let maxX = 0;
  let maxY = 0;
  for (const child of children) {
    const size = nodeSize(child);
    maxX = Math.max(maxX, child.position.x + size.width);
    maxY = Math.max(maxY, child.position.y + size.height);
  }
  const width = Math.max(
    MIN_GROUP_WIDTH,
    Math.round(maxX + GROUP_SIDE_PADDING),
  );
  const height = Math.max(
    MIN_GROUP_HEIGHT,
    Math.round(maxY + GROUP_SIDE_PADDING),
  );
  const nodes = state.nodes.map((node) => {
    if (node.id === groupId) {
      const {
        storyboardGroup: _group,
        storyboardAspect: _aspect,
        storyboardCols: _cols,
        storyboardShowIndex: _showIndex,
        storyboardBaseWidth: _baseWidth,
        storyboardBaseHeight: _baseHeight,
        ...data
      } = node.data;
      const { dragHandle: _dragHandle, ...rest } = node;
      return {
        ...rest,
        width,
        height,
        style: { ...node.style, width, height },
        data,
      };
    }
    if (node.parentId === groupId && node.hidden)
      return { ...node, hidden: false };
    return node;
  });
  const edges = restoreStoryboardEdges(
    state.edges,
    groupId,
    new Set(children.map((child) => child.id)),
  );
  return commitEdit(state, nodes, edges);
}

// ─── sibling duplicates ────────────────────────────────────────────────────

function siblingHeight(node: CanvasNode): number {
  return (
    node.measured?.height ??
    (typeof node.height === "number" ? node.height : UNMEASURED_SIBLING_HEIGHT)
  );
}

/**
 * Add a copy of a node `index` places below it (a multi-generation sibling),
 * with its incoming edges mirrored so the copy has the same upstream references.
 */
export function duplicateNodeAsSibling(
  state: CanvasGraphState,
  sourceId: string,
  index: number,
  deps: GroupDeps,
  dataOverrides: NodeData = {},
): { state: CanvasGraphState; nodeId: string | null } {
  const source = state.nodes.find((node) => node.id === sourceId);
  if (!source) return { state, nodeId: null };
  const created = createNode(
    deps.newId(),
    source.type,
    {
      x: source.position.x,
      y: source.position.y + (siblingHeight(source) + SIBLING_GAP) * index,
    },
    { ...source.data, ...dataOverrides },
  );
  const edges: CanvasEdge[] = state.edges
    .filter((edge) => edge.target === sourceId)
    .map((edge) => ({
      id: `e-${edge.source}-${created.id}`,
      source: edge.source,
      target: created.id,
      sourceHandle: edge.sourceHandle ?? "source",
      targetHandle: edge.targetHandle ?? "target",
      type: "disconnectableEdge",
    }))
    .filter((edge) => !state.edges.some((existing) => existing.id === edge.id));
  return {
    state: commitEdit(
      state,
      [...state.nodes, created],
      [...state.edges, ...edges],
    ),
    nodeId: created.id,
  };
}

/**
 * Copy nodes (and whole groups with their members) one place below the
 * originals. Members of a copied group follow the group's copy; edges between
 * copied nodes are rewired to the copies. The copies become the selection.
 */
export function duplicateNodesAsSiblings(
  state: CanvasGraphState,
  nodeIds: readonly string[],
  deps: GroupDeps,
): { state: CanvasGraphState; createdIds: string[] } {
  const sources = new Set(nodeIds);
  const created: CanvasNode[] = [];
  const createdIds: string[] = [];
  const idMap = new Map<string, string>();
  for (const sourceId of nodeIds) {
    const source = state.nodes.find((node) => node.id === sourceId);
    if (!source) continue;
    const parentCopied = Boolean(
      source.parentId && sources.has(source.parentId),
    );
    const position = parentCopied
      ? { x: source.position.x, y: source.position.y }
      : {
          x: source.position.x,
          y: source.position.y + siblingHeight(source) + SIBLING_GAP,
        };
    const renamed: NodeData = {};
    if (!parentCopied) {
      if (
        typeof source.data.displayName === "string" &&
        source.data.displayName
      ) {
        renamed.displayName = deps.naming.copy(source.data.displayName);
      }
      if (typeof source.data.label === "string" && source.data.label) {
        renamed.label = deps.naming.copy(source.data.label);
      }
    }
    let copy = createNode(deps.newId(), source.type, position, {
      ...source.data,
      ...renamed,
    });
    if (isGroupNode(source)) {
      copy = {
        ...copy,
        width: source.width,
        height: source.height,
        ...(source.style ? { style: { ...source.style } } : {}),
      };
    }
    if (source.parentId) {
      copy = {
        ...copy,
        parentId: idMap.get(source.parentId) ?? source.parentId,
        ...(source.extent ? { extent: source.extent } : {}),
      };
    }
    idMap.set(sourceId, copy.id);
    createdIds.push(copy.id);
    created.push(copy);
  }
  if (created.length === 0) return { state, createdIds: [] };
  const newEdges: CanvasEdge[] = [];
  for (const edge of state.edges) {
    const target = idMap.get(edge.target);
    if (!target) continue;
    const source = idMap.get(edge.source) ?? edge.source;
    newEdges.push({
      id: `e-${source}-${target}`,
      source,
      target,
      sourceHandle: edge.sourceHandle ?? "source",
      targetHandle: edge.targetHandle ?? "target",
      type: "disconnectableEdge",
    });
  }
  const nodes = [
    ...state.nodes.map((node) =>
      node.selected || sources.has(node.id)
        ? { ...node, selected: false }
        : node,
    ),
    ...created.map((node) => ({ ...node, selected: true })),
  ];
  const next = commitEdit(state, nodes, [...state.edges, ...newEdges]);
  return {
    state: {
      ...next,
      selectedNodeId: createdIds.length === 1 ? createdIds[0] : null,
    },
    createdIds,
  };
}
