/**
 * Browser recovery cache of the Creative Canvas.
 *
 * Ported from DramaClaw b299bfd9 (`features/freezone/canvasDraftStorage.ts` and
 * the hydrate decision of `useCanvasSync.ts`). The browser holds a recovery
 * copy only; the M8-A server revision is the durable content.
 *
 * Differences from the donor (spec §7):
 * - Entries are keyed by user, project and candidate, and a draft records the
 *   server revision it was edited from. The donor keys by project and canvas.
 * - The donor's separate undo-history mirror is not kept; the draft carries
 *   its own history.
 *
 * Unchanged: the content signature, the size cap with history shed first, the
 * seven-day expiry of every per-canvas entry, reclaiming malformed entries,
 * and the hydrate decision, which never applies a draft edited from another
 * revision: that draft becomes a conflict snapshot and the server content loads.
 */

import type { CanvasEdge, CanvasNode, HistoryState, MutationState } from "../domain/types";
import { isStaleByTtl, pruneLocalStorageByPrefix, registerStorageReclaimer, safeLocalStorageSet } from "./storageQuota";

export const DRAFT_MAX_BYTES = 1_500_000;
const DRAFT_VERSION = 1;
export const CANVAS_TTL_MS = 7 * 24 * 60 * 60 * 1_000;

const PREFIX = "arcreel:creative-canvas:";
const DRAFT_PREFIX = `${PREFIX}draft:`;
const CONFLICT_PREFIX = `${PREFIX}conflict:`;
const VIEWPORT_PREFIX = `${PREFIX}viewport:`;

export interface DraftScope {
  userId: string;
  projectName: string;
  candidateId: string;
}

export interface DraftInput {
  /** The server revision the local content was edited from; null before the first save. */
  baseRevision: number | null;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  viewport: unknown;
  metadata: Record<string, unknown> | null;
  history: HistoryState | null;
  mutation: MutationState;
  updatedAt: number;
}

export interface StoredDraft extends DraftInput, DraftScope {
  version: typeof DRAFT_VERSION;
  signature: string;
}

export interface ConflictSnapshot {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  viewport: unknown;
  metadata: Record<string, unknown> | null;
  /** ISO time of the conflicting local edit. */
  timestamp: string;
}

function scopeKey(prefix: string, scope: DraftScope): string {
  return `${prefix}${encodeURIComponent(scope.userId)}:${encodeURIComponent(scope.projectName)}:${encodeURIComponent(scope.candidateId)}`;
}

// ─── signatures ────────────────────────────────────────────────────────────

function sortJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortJsonValue);
  if (!value || typeof value !== "object") return value;
  const input = value as Record<string, unknown>;
  const output: Record<string, unknown> = {};
  for (const key of Object.keys(input).sort()) {
    const item = input[key];
    if (item !== undefined) output[key] = sortJsonValue(item);
  }
  return output;
}

/** Order-independent signature of the recoverable content (nodes, edges, metadata). */
export function draftSignature(
  nodes: readonly CanvasNode[],
  edges: readonly CanvasEdge[],
  metadata: Record<string, unknown> | null,
): string {
  return JSON.stringify(
    sortJsonValue({
      nodes: nodes.map((node) => ({
        id: node.id,
        type: node.type,
        position: node.position,
        width: node.width,
        height: node.height,
        style: node.style,
        parentId: node.parentId,
        extent: node.extent,
        data: node.data,
      })),
      edges: edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle,
        targetHandle: edge.targetHandle,
        type: edge.type,
        data: edge.data,
      })),
      metadata: metadata ?? null,
    }),
  );
}

/** Signature of nodes and edges in their stored order (the donor's content comparison). */
function contentSignature(nodes: readonly CanvasNode[], edges: readonly CanvasEdge[]): string {
  const nodePart = nodes
    .map((node) =>
      JSON.stringify({
        id: node.id,
        type: node.type,
        position: node.position,
        width: node.width,
        height: node.height,
        style: node.style,
        parentId: node.parentId,
        extent: node.extent,
        data: node.data,
      }),
    )
    .join("");
  const edgePart = edges
    .map((edge) =>
      JSON.stringify({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle,
        targetHandle: edge.targetHandle,
        type: edge.type,
        data: edge.data,
      }),
    )
    .join("");
  return `${nodePart}${edgePart}`;
}

/** True when every value in `subset` appears at the same place in `superset`. */
function jsonContainsSubset(superset: unknown, subset: unknown): boolean {
  if (subset === undefined) return true;
  if (subset === null || typeof subset !== "object") return Object.is(superset, subset);
  if (Array.isArray(subset)) {
    if (!Array.isArray(superset) || superset.length < subset.length) return false;
    return subset.every((item, index) => jsonContainsSubset(superset[index], item));
  }
  if (!superset || typeof superset !== "object" || Array.isArray(superset)) return false;
  const supersetRecord = superset as Record<string, unknown>;
  const subsetRecord = subset as Record<string, unknown>;
  return Object.keys(subsetRecord).every((key) => jsonContainsSubset(supersetRecord[key], subsetRecord[key]));
}

// ─── drafts ────────────────────────────────────────────────────────────────

function isMutationState(value: unknown): value is MutationState {
  if (!value || typeof value !== "object") return false;
  const mutation = value as Partial<MutationState>;
  return (
    typeof mutation.userEditsSinceHydrate === "number" &&
    (mutation.lastMutationSource === null ||
      mutation.lastMutationSource === "user_edit" ||
      mutation.lastMutationSource === "delete_to_empty" ||
      mutation.lastMutationSource === "manual_clear") &&
    typeof mutation.pendingClearIntent === "boolean"
  );
}

function parseDraft(value: unknown, scope: DraftScope): StoredDraft | null {
  if (!value || typeof value !== "object") return null;
  const draft = value as Partial<StoredDraft>;
  if (
    draft.version !== DRAFT_VERSION ||
    draft.userId !== scope.userId ||
    draft.projectName !== scope.projectName ||
    draft.candidateId !== scope.candidateId ||
    !Array.isArray(draft.nodes) ||
    !Array.isArray(draft.edges) ||
    typeof draft.signature !== "string" ||
    typeof draft.updatedAt !== "number" ||
    !(typeof draft.baseRevision === "number" || draft.baseRevision === null) ||
    !isMutationState(draft.mutation)
  ) {
    return null;
  }
  const history =
    draft.history &&
    typeof draft.history === "object" &&
    Array.isArray((draft.history as Partial<HistoryState>).past) &&
    Array.isArray((draft.history as Partial<HistoryState>).future)
      ? draft.history
      : null;
  return {
    version: DRAFT_VERSION,
    ...scope,
    baseRevision: draft.baseRevision,
    nodes: draft.nodes,
    edges: draft.edges,
    viewport: draft.viewport ?? null,
    metadata: draft.metadata ?? null,
    history,
    mutation: draft.mutation,
    updatedAt: draft.updatedAt,
    signature: draft.signature,
  };
}

export function readDraft(scope: DraftScope): StoredDraft | null {
  try {
    const raw = localStorage.getItem(scopeKey(DRAFT_PREFIX, scope));
    if (!raw) return null;
    return parseDraft(JSON.parse(raw) as unknown, scope);
  } catch {
    return null;
  }
}

export function clearDraft(scope: DraftScope): void {
  try {
    localStorage.removeItem(scopeKey(DRAFT_PREFIX, scope));
  } catch {
    // Best-effort cleanup.
  }
}

/**
 * Store the recovery copy. When it exceeds the cap, the history is dropped
 * first; if the content alone is still too large, no draft is kept (a partial
 * draft would look recoverable and is not). Returns whether a draft was stored.
 */
export function writeDraft(scope: DraftScope, input: DraftInput): boolean {
  const draft: StoredDraft = {
    version: DRAFT_VERSION,
    ...scope,
    ...input,
    signature: draftSignature(input.nodes, input.edges, input.metadata),
  };
  const key = scopeKey(DRAFT_PREFIX, scope);
  try {
    const serialized = JSON.stringify(draft);
    if (serialized.length <= DRAFT_MAX_BYTES && safeLocalStorageSet(key, serialized)) return true;
  } catch {
    // Fall through to the draft without history.
  }
  try {
    const serialized = JSON.stringify({ ...draft, history: null });
    if (serialized.length <= DRAFT_MAX_BYTES && safeLocalStorageSet(key, serialized)) return true;
    clearDraft(scope);
    return false;
  } catch {
    clearDraft(scope);
    return false;
  }
}

// ─── conflict snapshots and viewports ──────────────────────────────────────

export function writeConflictSnapshot(scope: DraftScope, snapshot: ConflictSnapshot): boolean {
  try {
    return safeLocalStorageSet(scopeKey(CONFLICT_PREFIX, scope), JSON.stringify(snapshot));
  } catch {
    return false;
  }
}

export function readConflictSnapshot(scope: DraftScope): ConflictSnapshot | null {
  try {
    const raw = localStorage.getItem(scopeKey(CONFLICT_PREFIX, scope));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ConflictSnapshot>;
    if (!Array.isArray(parsed.nodes) || !Array.isArray(parsed.edges) || typeof parsed.timestamp !== "string") {
      return null;
    }
    return {
      nodes: parsed.nodes,
      edges: parsed.edges,
      viewport: parsed.viewport ?? null,
      metadata: parsed.metadata ?? null,
      timestamp: parsed.timestamp,
    };
  } catch {
    return null;
  }
}

export function clearConflictSnapshot(scope: DraftScope): void {
  try {
    localStorage.removeItem(scopeKey(CONFLICT_PREFIX, scope));
  } catch {
    // Best-effort cleanup.
  }
}

export function writeStoredViewport(scope: DraftScope, viewport: { x: number; y: number; zoom: number }): boolean {
  return safeLocalStorageSet(scopeKey(VIEWPORT_PREFIX, scope), JSON.stringify(viewport));
}

export function readStoredViewport(scope: DraftScope): { x: number; y: number; zoom: number } | null {
  try {
    const raw = localStorage.getItem(scopeKey(VIEWPORT_PREFIX, scope));
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<{ x: number; y: number; zoom: number }>;
    return typeof value.x === "number" && typeof value.y === "number" && typeof value.zoom === "number"
      ? { x: value.x, y: value.y, zoom: value.zoom }
      : null;
  } catch {
    return null;
  }
}

// ─── pruning ───────────────────────────────────────────────────────────────

function isCanvasKey(key: string): boolean {
  return key.startsWith(DRAFT_PREFIX) || key.startsWith(CONFLICT_PREFIX) || key.startsWith(VIEWPORT_PREFIX);
}

function entryTimestamp(key: string, parsed: unknown): number | null {
  if (!parsed || typeof parsed !== "object") return null;
  if (key.startsWith(CONFLICT_PREFIX)) {
    const timestamp = (parsed as { timestamp?: unknown }).timestamp;
    if (typeof timestamp !== "string") return null;
    const ms = Date.parse(timestamp);
    return Number.isNaN(ms) ? null : ms;
  }
  const updatedAt = (parsed as { updatedAt?: unknown }).updatedAt;
  return typeof updatedAt === "number" ? updatedAt : null;
}

function shouldReclaim(key: string, raw: string, now: number): boolean {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return true;
  }
  // Viewports are tiny and carry no timestamp: reclaim only when unusable.
  if (key.startsWith(VIEWPORT_PREFIX)) return !parsed || typeof parsed !== "object";
  const timestamp = entryTimestamp(key, parsed);
  if (timestamp == null) return true;
  return isStaleByTtl(timestamp, now, CANVAS_TTL_MS);
}

/** Drop every per-canvas entry that is malformed or older than seven days. */
export function pruneCanvasStorage(now = Date.now()): void {
  pruneLocalStorageByPrefix(isCanvasKey, (key, raw) => shouldReclaim(key, raw, now));
}

// A write under quota pressure anywhere frees stale canvas entries first.
registerStorageReclaimer(() => {
  pruneCanvasStorage();
});

// ─── hydrate decision ──────────────────────────────────────────────────────

export type DraftRecoveryDecision =
  | { kind: "remote" }
  | { kind: "draft"; draft: StoredDraft }
  | { kind: "conflict"; draft: StoredDraft };

/**
 * What to load when a canvas opens, given the local draft and the server's
 * current revision:
 *
 * - no draft, or a draft with the server's content: the server content;
 * - a draft edited from the server's current revision: the draft (its edits
 *   are then saved normally);
 * - a draft edited from another revision: a conflict. The caller keeps the
 *   draft as a conflict snapshot and loads the server content; neither side
 *   is overwritten automatically.
 */
export function decideDraftRecovery(
  draft: StoredDraft | null,
  remoteRevision: number | null,
  remoteNodes: readonly CanvasNode[],
  remoteEdges: readonly CanvasEdge[],
  remoteMetadata: Record<string, unknown> | null,
): DraftRecoveryDecision {
  if (!draft) return { kind: "remote" };
  if (draft.signature === draftSignature(remoteNodes, remoteEdges, remoteMetadata)) return { kind: "remote" };
  const alreadySaved =
    contentSignature(draft.nodes, draft.edges) === contentSignature(remoteNodes, remoteEdges) &&
    jsonContainsSubset(remoteMetadata ?? null, draft.metadata ?? null);
  if (alreadySaved) return { kind: "remote" };
  if (typeof draft.baseRevision === "number" && typeof remoteRevision === "number" && draft.baseRevision === remoteRevision) {
    return { kind: "draft", draft };
  }
  return { kind: "conflict", draft };
}
