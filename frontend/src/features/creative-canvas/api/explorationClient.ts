/**
 * The M8 exploration routes a Canvas uses. Every call takes an AbortSignal; a
 * failed call rejects with `ApiRequestError`, whose `status` feeds
 * `classifySaveOutcome`.
 */

import { API } from "@/api";

import { digestPayload } from "./canonical";
import type {
  CandidateHead,
  CanvasCandidateWire,
  CanvasRevisionWire,
  ExplorationContext,
  Sha256Digest,
} from "./types";

interface CallOptions {
  signal?: AbortSignal;
}

function base(projectName: string): string {
  return `/projects/${encodeURIComponent(projectName)}/m8/exploration`;
}

/** The candidate id of an episode's Canvas; one Canvas per episode. */
export function canvasCandidateId(episode: number): string {
  return `canvas-episode-${episode}`;
}

export function getExplorationContext(
  projectName: string,
  episode: number,
  options: CallOptions = {},
): Promise<ExplorationContext> {
  return API.request(`${base(projectName)}/context?episode=${episode}`, { signal: options.signal });
}

export function getCandidateHead(
  projectName: string,
  candidateId: string,
  options: CallOptions = {},
): Promise<CandidateHead> {
  return API.request(`${base(projectName)}/candidates/${encodeURIComponent(candidateId)}`, {
    signal: options.signal,
  });
}

export function getCanvasRevision(
  projectName: string,
  candidateId: string,
  revision: number,
  options: CallOptions = {},
): Promise<CanvasRevisionWire> {
  return API.request(
    `${base(projectName)}/candidates/${encodeURIComponent(candidateId)}/revisions/${revision}`,
    { signal: options.signal },
  );
}

export interface AppendCanvasInput {
  projectName: string;
  candidateId: string;
  context: ExplorationContext;
  payload: CanvasCandidateWire;
  /** The head the edit started from; null for the first save. */
  head: CandidateHead | null;
  commandId: string;
  now: Date;
}

/** Build the revision a save appends. Separate from the call so a retry resends the same bytes. */
export async function buildCanvasRevision(input: AppendCanvasInput): Promise<CanvasRevisionWire> {
  const payloadDigest = (await digestPayload(input.payload, input.context.lineage)) as Sha256Digest;
  return {
    candidate_id: input.candidateId,
    revision: input.head ? input.head.current_revision + 1 : 1,
    kind: "CANVAS",
    parent_revision: input.head ? input.head.current_revision : null,
    payload: input.payload,
    payload_digest: payloadDigest,
    lineage: input.context.lineage,
    created_by: input.context.created_by,
    created_at: input.now.toISOString(),
  };
}

export function appendCanvasRevision(
  projectName: string,
  revision: CanvasRevisionWire,
  expectedHeadVersion: number | null,
  commandId: string,
  options: CallOptions = {},
): Promise<CandidateHead> {
  return API.request(`${base(projectName)}/revisions`, {
    method: "POST",
    body: JSON.stringify({ candidate: revision, expected_head_version: expectedHeadVersion, command_id: commandId }),
    signal: options.signal,
  });
}
