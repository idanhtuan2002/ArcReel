/**
 * Pure Creative Canvas graph types. No React, Zustand, API or storage imports.
 *
 * The node and edge shapes follow what the React Flow adapter renders; the API
 * layer maps them to and from the M8 `CanvasCandidate` contract.
 */

/** Node types of the ArcReel Canvas v1. Media nodes reference existing assets only. */
export const CANVAS_NODE_TYPES = ["beat", "note", "frame", "clip", "audio", "group"] as const;
export type CanvasNodeType = (typeof CANVAS_NODE_TYPES)[number];

export interface XY {
  x: number;
  y: number;
}

export interface CanvasNode {
  id: string;
  type: CanvasNodeType;
  position: XY;
  width?: number;
  height?: number;
  parentId?: string;
  extent?: "parent";
  data: Record<string, unknown>;
}

export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
  type?: string;
  data?: Record<string, unknown>;
}

export interface HistorySnapshot {
  nodes: readonly CanvasNode[];
  edges: readonly CanvasEdge[];
}

export interface HistoryState {
  past: readonly HistorySnapshot[];
  future: readonly HistorySnapshot[];
}

/**
 * Why the content was last mutated.
 *
 * - `user_edit`: a normal edit.
 * - `delete_to_empty`: a removal that left zero nodes, treated as an implicit clear.
 * - `manual_clear`: an explicit clear.
 * - `null`: freshly loaded, no edit yet.
 */
export type MutationSource = "user_edit" | "delete_to_empty" | "manual_clear";

export interface MutationState {
  userEditsSinceHydrate: number;
  lastMutationSource: MutationSource | null;
  pendingClearIntent: boolean;
}

export interface CanvasGraphState extends MutationState {
  nodes: readonly CanvasNode[];
  edges: readonly CanvasEdge[];
  selectedNodeId: string | null;
  history: HistoryState;
  /** The snapshot taken at the first move of a drag or resize, pushed when it ends. */
  dragSnapshot: HistorySnapshot | null;
}

export type NodeChange =
  | { type: "position"; id: string; position?: XY; dragging?: boolean }
  | { type: "dimensions"; id: string; dimensions?: { width: number; height: number }; resizing?: boolean }
  | { type: "select"; id: string; selected: boolean }
  | { type: "remove"; id: string };

export interface Connection {
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}
