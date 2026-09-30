/**
 * Which ids a batch delete or duplicate of the current selection really acts on.
 * Ported from DramaClaw b299bfd9 (`features/canvas/domain/groupSelectionDelete.ts`
 * and `groupSelectionDuplicate.ts`), without the donor's preset-managed locks.
 *
 * The canvas marquee drops a group that encloses other hit nodes from the
 * selection, so dragging a multi-selection does not move parent and child twice.
 * A group whose every child is selected is therefore added back: deleting would
 * leave it an empty frame, and duplicating would scatter its copied members back
 * into the original group.
 */

import type { CanvasNode } from "./types";

/** The ids a batch delete removes. The reducer cascades to descendants, so groups need only be added. */
export function collectBatchDeletableIds(
  nodes: readonly CanvasNode[],
  selectedIds: Iterable<string>,
): string[] {
  const selected = new Set(selectedIds);
  const deletable = new Set<string>();
  for (const node of nodes) {
    if (selected.has(node.id)) deletable.add(node.id);
  }
  const tally = new Map<string, { total: number; selected: number }>();
  for (const node of nodes) {
    if (!node.parentId) continue;
    const entry = tally.get(node.parentId) ?? { total: 0, selected: 0 };
    entry.total += 1;
    if (selected.has(node.id)) entry.selected += 1;
    tally.set(node.parentId, entry);
  }
  for (const node of nodes) {
    if (node.type !== "group" || deletable.has(node.id)) continue;
    const entry = tally.get(node.id);
    if (entry && entry.total > 0 && entry.total === entry.selected)
      deletable.add(node.id);
  }
  return Array.from(deletable);
}

/** Number of ancestors of a node, guarded against a parent cycle in corrupt data. */
function depthOf(
  node: CanvasNode,
  byId: ReadonlyMap<string, CanvasNode>,
): number {
  let depth = 0;
  const visited = new Set<string>([node.id]);
  let parentId = node.parentId;
  while (parentId && !visited.has(parentId)) {
    visited.add(parentId);
    depth += 1;
    parentId = byId.get(parentId)?.parentId;
  }
  return depth;
}

/**
 * The ids a batch duplicate copies, in pre-order (a parent before its members),
 * so the duplicate can re-point members at the cloned group. Nested groups are
 * resolved deepest first, so an outer group sees its inner group as covered.
 */
export function collectDuplicableIds(
  nodes: readonly CanvasNode[],
  selectedIds: Iterable<string>,
): string[] {
  const selected = new Set(selectedIds);
  const byId = new Map(nodes.map((node) => [node.id, node] as const));
  const result = new Set<string>();
  for (const node of nodes) {
    if (selected.has(node.id)) result.add(node.id);
  }
  const children = new Map<string, CanvasNode[]>();
  for (const node of nodes) {
    if (!node.parentId) continue;
    const siblings = children.get(node.parentId);
    if (siblings) siblings.push(node);
    else children.set(node.parentId, [node]);
  }
  const groups = nodes
    .filter((node) => node.type === "group")
    .map((node) => ({ node, depth: depthOf(node, byId) }))
    .sort((a, b) => b.depth - a.depth);
  for (const { node } of groups) {
    if (result.has(node.id)) continue;
    const members = children.get(node.id);
    if (
      members &&
      members.length > 0 &&
      members.every((member) => result.has(member.id))
    ) {
      result.add(node.id);
    }
  }
  return nodes
    .filter((node) => result.has(node.id))
    .map((node) => ({ id: node.id, depth: depthOf(node, byId) }))
    .sort((a, b) => a.depth - b.depth)
    .map((entry) => entry.id);
}
