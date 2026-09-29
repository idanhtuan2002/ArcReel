/**
 * Node geometry shared by the graph reducers. Ported from DramaClaw b299bfd9
 * (`stores/canvasStore.ts`: resolveAbsolutePosition, getNodeSize, FALLBACK_NODE_SIZES).
 */

import type { CanvasNode, CanvasNodeType, XY } from "./types";

export const DEFAULT_NODE_WIDTH = 320;
const DEFAULT_NODE_HEIGHT = 200;

/** Size used before a node is measured, per node type (the donor sizes of the matching donor types; frames use the default like donor export-image frames). */
const FALLBACK_NODE_SIZES: Partial<
  Record<CanvasNodeType, { width: number; height: number }>
> = {
  beat: { width: 440, height: 320 },
  note: { width: 440, height: 320 },
  clip: { width: 580, height: 380 },
  audio: { width: 480, height: 210 },
};

/** Position in canvas coordinates: the node's position plus every ancestor's, cycle-safe. */
export function resolveAbsolutePosition(
  node: CanvasNode,
  byId: ReadonlyMap<string, CanvasNode>,
): XY {
  let x = node.position.x;
  let y = node.position.y;
  let parentId = node.parentId;
  const visited = new Set<string>();
  while (parentId && !visited.has(parentId)) {
    visited.add(parentId);
    const parent = byId.get(parentId);
    if (!parent) break;
    x += parent.position.x;
    y += parent.position.y;
    parentId = parent.parentId;
  }
  return { x, y };
}

/** Measured size, else explicit width/height, else the type fallback. */
export function nodeSize(node: CanvasNode): { width: number; height: number } {
  const fallback = FALLBACK_NODE_SIZES[node.type];
  return {
    width:
      typeof node.measured?.width === "number"
        ? node.measured.width
        : typeof node.width === "number"
          ? node.width
          : (fallback?.width ?? DEFAULT_NODE_WIDTH),
    height:
      typeof node.measured?.height === "number"
        ? node.measured.height
        : typeof node.height === "number"
          ? node.height
          : (fallback?.height ?? DEFAULT_NODE_HEIGHT),
  };
}

export function isGroupNode(
  node: CanvasNode | null | undefined,
): node is CanvasNode {
  return node?.type === "group";
}

export function isStoryboardGroupNode(
  node: CanvasNode | null | undefined,
): node is CanvasNode {
  return isGroupNode(node) && node.data.storyboardGroup === true;
}
