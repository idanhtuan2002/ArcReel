/**
 * Pure save-protocol decisions of the Creative Canvas.
 *
 * `decideSaveAction`, the payload caps and `checkPayloadLimits` are ported
 * unchanged from DramaClaw b299bfd9 (`features/freezone/canvasSyncCore.ts`).
 * `classifySaveOutcome` replaces the donor's `classifySaveError`: ArcReel saves
 * through the M8-A exploration API, whose failures are 404 (unknown or foreign
 * candidate), 409 (the candidate head moved, or a reused command), 422
 * (invalid body) and transient failures. Every M8-A error body carries a
 * localized `detail`, which is shown as is.
 */

import type { MutationSource } from "../domain/types";

/**
 * Caps on the content one save sends. Node and edge counts that high only come
 * from runaway loops, so they stop autosave with an error. The body size is
 * advisory: over it, the save is still sent and the server decides.
 */
export const MAX_NODES = 50_000;
export const MAX_EDGES = 200_000;
export const MAX_BODY_BYTES = 5 * 1024 * 1024;

/** Everything `decideSaveAction` needs, collected when the debounced save fires. */
export interface SaveSnapshot {
  /** False while the initial load is still in flight. */
  hydrated: boolean;
  /** True while the canvas or project is changing. */
  switching: boolean;
  nodeCount: number;
  edgeCount: number;
  /** Node count of the last server revision loaded or saved. */
  lastRemoteNodeCount: number;
  userEditsSinceHydrate: number;
  lastMutationSource: MutationSource | null;
  pendingClearIntent: boolean;
}

export type SaveSource = "autosave" | "manual_clear";

export type SaveDecision =
  | { kind: "skip"; reason: "not_hydrated" | "switching" }
  | { kind: "block"; reason: "dangerous_empty"; lastRemoteNodeCount: number }
  | { kind: "send"; saveSource: SaveSource; allowEmptyOverwrite: boolean };

/**
 * Five-state decision, applied each time the debounced save fires:
 *
 * 1. not loaded yet: skip;
 * 2. switching canvas or project: skip;
 * 3. local empty, server non-empty, explicit clear intent: send as `manual_clear`;
 * 4. local empty, server non-empty, emptied by deleting nodes (`delete_to_empty`):
 *    send as `manual_clear` too, without a dedicated clear button;
 * 5. local empty, server non-empty, no clear intent: block (`dangerous_empty`),
 *    which catches a store reset that emptied the canvas without user input.
 *
 * Every other case sends a normal autosave.
 */
export function decideSaveAction(snap: SaveSnapshot): SaveDecision {
  if (!snap.hydrated) {
    return { kind: "skip", reason: "not_hydrated" };
  }
  if (snap.switching) {
    return { kind: "skip", reason: "switching" };
  }

  const localEmpty = snap.nodeCount === 0;
  const remoteWasNonEmpty = snap.lastRemoteNodeCount > 0;

  if (localEmpty && remoteWasNonEmpty) {
    if (snap.pendingClearIntent || snap.lastMutationSource === "manual_clear") {
      return { kind: "send", saveSource: "manual_clear", allowEmptyOverwrite: true };
    }
    if (snap.lastMutationSource === "delete_to_empty") {
      return { kind: "send", saveSource: "manual_clear", allowEmptyOverwrite: true };
    }
    return { kind: "block", reason: "dangerous_empty", lastRemoteNodeCount: snap.lastRemoteNodeCount };
  }

  return { kind: "send", saveSource: "autosave", allowEmptyOverwrite: false };
}

export interface PayloadLimitViolation {
  field: "nodes" | "edges" | "body";
  actual: number;
  limit: number;
}

/**
 * Check a save against the caps. Returns the first violated field, or `null`.
 * `serializedSize` is optional so a caller can check the counts first and only
 * serialize when they pass.
 */
export function checkPayloadLimits(
  nodeCount: number,
  edgeCount: number,
  serializedSize: number | null,
): PayloadLimitViolation | null {
  if (nodeCount > MAX_NODES) {
    return { field: "nodes", actual: nodeCount, limit: MAX_NODES };
  }
  if (edgeCount > MAX_EDGES) {
    return { field: "edges", actual: edgeCount, limit: MAX_EDGES };
  }
  if (serializedSize != null && serializedSize > MAX_BODY_BYTES) {
    return { field: "body", actual: serializedSize, limit: MAX_BODY_BYTES };
  }
  return null;
}

export type Translate = (key: string, params?: Record<string, unknown>) => string;

/** The user-facing message of a payload-limit violation. */
export function describePayloadViolation(violation: PayloadLimitViolation, t: Translate): string {
  if (violation.field === "nodes") {
    return t("creativeCanvas.save.nodesOverLimit", { actual: violation.actual, limit: violation.limit });
  }
  if (violation.field === "edges") {
    return t("creativeCanvas.save.edgesOverLimit", { actual: violation.actual, limit: violation.limit });
  }
  return t("creativeCanvas.save.bodyOverLimit", {
    actual: Math.round(violation.actual / 1024),
    limit: Math.round(violation.limit / 1024),
  });
}

export type SaveOutcome =
  | { kind: "conflict"; message: string }
  | { kind: "not_found"; message: string }
  | { kind: "invalid"; message: string }
  | { kind: "retry"; message: string }
  | { kind: "error"; message: string };

/**
 * Map a failed M8-A save to the action the canvas takes.
 *
 * - 409: the candidate head moved (another tab or user saved first). The canvas
 *   stops autosaving and shows the conflict; it never overwrites the server or
 *   the local draft automatically.
 * - 404: the candidate is unknown in this scope; nothing to retry.
 * - 422: the body was rejected; retrying the same content cannot succeed.
 * - no status (network), 408, 429, 5xx: transient; retry later.
 */
export function classifySaveOutcome(
  status: number | null,
  body: { detail?: unknown } | undefined,
  fallbackMessage: string,
): SaveOutcome {
  const message = typeof body?.detail === "string" && body.detail ? body.detail : fallbackMessage;
  if (status === 409) return { kind: "conflict", message };
  if (status === 404) return { kind: "not_found", message };
  if (status === 422) return { kind: "invalid", message };
  if (status === null || status === 408 || status === 429 || status >= 500) return { kind: "retry", message };
  return { kind: "error", message };
}
