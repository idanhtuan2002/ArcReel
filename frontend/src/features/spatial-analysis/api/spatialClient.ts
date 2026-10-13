/**
 * The M8 spatial routes: approved video sources, frame receipts, one spatial
 * analysis, and the revision it appended. A failed call rejects with
 * `ApiRequestError`.
 */

import { API } from "@/api";

interface CallOptions {
  signal?: AbortSignal;
}

export interface SpatialSource {
  artifact_key: string;
  shot_id: string;
  master_version: number;
}

export interface FrameReceipt {
  receipt_id: string;
  receipt_digest: string;
  parent_artifact_key: string;
  parent_master_version: number;
  frame_content_digest: string;
}

export interface FrameRef {
  receipt_id: string;
  receipt_digest: string;
}

export interface CandidateHead {
  candidate_id: string;
  current_revision: number;
  head_version: number;
}

export type EvidenceClass = "VISIBLE" | "INFERRED" | "GAP";

export interface SpatialAssertion {
  assertion_id: string;
  evidence_class: EvidenceClass;
  source_refs: string[];
  relation: string;
  subject_refs: string[];
  confidence: number | null;
  warnings: string[];
}

export interface SpatialRevision {
  candidate_id: string;
  revision: number;
  payload: { kind: "SPATIAL"; spatial: { assertions: SpatialAssertion[] } };
}

export interface ExecuteSpatialInput {
  commandId: string;
  candidateId: string;
  episode: number;
  sceneName: string;
  master: FrameRef;
  reverse: FrameRef;
}

function base(projectName: string): string {
  return `/projects/${encodeURIComponent(projectName)}/m8`;
}

export function listSpatialSources(
  projectName: string,
  episode: number,
  options: CallOptions = {},
): Promise<SpatialSource[]> {
  return API.request(`${base(projectName)}/spatial/sources?episode=${episode}`, { signal: options.signal });
}

/** The frame command is derived from its inputs, so a repeated request replays the same receipt. */
export function frameCommandId(source: SpatialSource, frameIndex: number): string {
  return `frame:${source.artifact_key}:${source.master_version}:${frameIndex}`;
}

export function deriveSpatialFrame(
  projectName: string,
  source: SpatialSource,
  frameIndex: number,
  options: CallOptions = {},
): Promise<FrameReceipt> {
  return API.request(`${base(projectName)}/spatial/frames`, {
    method: "POST",
    body: JSON.stringify({
      parent_artifact_key: source.artifact_key,
      expected_master_version: source.master_version,
      decoded_frame_index: frameIndex,
      command_id: frameCommandId(source, frameIndex),
    }),
    signal: options.signal,
  });
}

export function executeSpatial(
  projectName: string,
  input: ExecuteSpatialInput,
  options: CallOptions = {},
): Promise<CandidateHead> {
  return API.request(`${base(projectName)}/spatial/executions`, {
    method: "POST",
    body: JSON.stringify({
      command_id: input.commandId,
      candidate_id: input.candidateId,
      expected_head_version: null,
      episode: input.episode,
      scene_name: input.sceneName,
      master: input.master,
      reverse: input.reverse,
    }),
    signal: options.signal,
  });
}

export function getSpatialRevision(
  projectName: string,
  head: CandidateHead,
  options: CallOptions = {},
): Promise<SpatialRevision> {
  return API.request(
    `${base(projectName)}/exploration/candidates/${encodeURIComponent(head.candidate_id)}/revisions/${head.current_revision}`,
    { signal: options.signal },
  );
}
