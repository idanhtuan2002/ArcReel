/**
 * The Canvas graph as an M8 `CanvasCandidate` payload and back.
 *
 * Each node and edge keeps its persistent fields in `body`; selection and
 * measured sizes are view state and are not saved. `groups` and
 * `storyboard_order` are projections of the group nodes, recomputed on every
 * save, so a reader of the revision does not need to replay the layout. A load
 * rebuilds the graph from `nodes` and `edges` alone.
 */

import { isGroupNode, isStoryboardGroupNode } from "../domain/geometry";
import { membersInReadingOrder } from "../domain/groups";
import { BOOKMARK_SLOT_COUNT, createEmptyBookmarks, type ViewportBookmarks } from "../domain/bookmarks";
import { CANVAS_NODE_TYPES, type CanvasEdge, type CanvasNode, type CanvasNodeType } from "../domain/types";
import type { CanvasCandidateWire, JsonObject } from "./types";

export const GRAPH_SCHEMA_VERSION = "1";
const DEFAULT_EDGE_TYPE = "default";

/** The JSON a value becomes on the wire; undefined members and functions disappear. */
function wire(value: object): JsonObject {
  return JSON.parse(JSON.stringify(value)) as JsonObject;
}

export function toCanvasPayload(
  nodes: readonly CanvasNode[],
  edges: readonly CanvasEdge[],
  bookmarks: ViewportBookmarks,
): CanvasCandidateWire {
  const groups = nodes.filter((node) => isGroupNode(node));
  return {
    kind: "CANVAS",
    graph_schema_version: GRAPH_SCHEMA_VERSION,
    nodes: nodes.map((node) => {
      const { id, type, selected: _selected, measured: _measured, ...body } = node;
      return { node_id: id, node_type: type, body: wire(body) };
    }),
    edges: edges.map((edge) => {
      const { id, source, target, type, ...body } = edge;
      return {
        edge_id: id,
        source_node_id: source,
        target_node_id: target,
        edge_type: type ?? DEFAULT_EDGE_TYPE,
        body: wire(body),
      };
    }),
    groups: groups.map((group) => ({
      group_id: group.id,
      member_ids: membersInReadingOrder(nodes, group.id).map((node) => node.id),
      storyboard: isStoryboardGroupNode(group),
    })),
    storyboard_order: groups
      .filter((group) => isStoryboardGroupNode(group))
      .flatMap((group) => membersInReadingOrder(nodes, group.id).map((node) => node.id)),
    viewport_bookmarks: bookmarks.flatMap((bookmark, slot) =>
      bookmark ? [{ slot, x: bookmark.x, y: bookmark.y, zoom: bookmark.zoom }] : [],
    ),
  };
}

function isNodeType(value: string): value is CanvasNodeType {
  return (CANVAS_NODE_TYPES as readonly string[]).includes(value);
}

export interface LoadedCanvas {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  bookmarks: ViewportBookmarks;
}

/** Rebuild the graph from a saved payload. Nodes of an unknown type, and edges touching them, are skipped. */
export function fromCanvasPayload(payload: CanvasCandidateWire): LoadedCanvas {
  const nodes: CanvasNode[] = [];
  for (const item of payload.nodes) {
    if (!isNodeType(item.node_type)) continue;
    nodes.push({ ...(item.body as unknown as Omit<CanvasNode, "id" | "type">), id: item.node_id, type: item.node_type });
  }
  const known = new Set(nodes.map((node) => node.id));
  const edges: CanvasEdge[] = payload.edges
    .filter((item) => known.has(item.source_node_id) && known.has(item.target_node_id))
    .map((item) => ({
      ...(item.body as unknown as Omit<CanvasEdge, "id" | "source" | "target">),
      id: item.edge_id,
      source: item.source_node_id,
      target: item.target_node_id,
      ...(item.edge_type === DEFAULT_EDGE_TYPE ? {} : { type: item.edge_type }),
    }));
  const bookmarks = createEmptyBookmarks();
  for (const item of payload.viewport_bookmarks) {
    const { slot, x, y, zoom } = item;
    if (
      typeof slot === "number" &&
      Number.isInteger(slot) &&
      slot >= 0 &&
      slot < BOOKMARK_SLOT_COUNT &&
      typeof x === "number" &&
      typeof y === "number" &&
      typeof zoom === "number"
    ) {
      bookmarks[slot] = { x, y, zoom };
    }
  }
  return { nodes, edges, bookmarks };
}
