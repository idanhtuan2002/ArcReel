/**
 * The M8-C shot workflow routes: Shot target state, LOCATION binding, frame review, pair decision,
 * typed spatial promotion and Gate C approval of a generated shot. Shot generation itself is queued
 * through `enqueueR2Shot` in the actions layer. A failed call rejects with `ApiRequestError`.
 */

import { API, ApiRequestError } from "@/api";

import type { CandidateHead, FrameRef } from "./spatialClient";

interface CallOptions {
  signal?: AbortSignal;
}

export type ReviewRole = "MASTER" | "REVERSE";

export interface TargetVersionRef {
  target_type: "SCENE" | "SHOT";
  target_id: string;
  registry_version: number;
  version_digest: string;
}

export interface ShotTargetState {
  target_ref: TargetVersionRef;
  purpose: string;
  target_duration: number;
  location_ref: string | null;
  binding: {
    status: "none" | "stale" | "current";
    binding_id: string | null;
    binding_version: number | null;
    snapshot_digest: string | null;
    target_registry_version: number | null;
    has_spatial_set: boolean;
  };
  pair: {
    status: "unavailable" | "none" | "approved";
    binding_version: number | null;
    /** The approved pair's frames, MASTER then REVERSE. */
    views: { role: ReviewRole; receipt_id: string; receipt_digest: string }[];
  };
  shot: { task_id: string; status: string } | null;
  master_version: number | null;
}

export interface ReviewFrame {
  role: ReviewRole;
  receipt_id: string;
  receipt_digest: string;
  png_digest: string;
}

export interface ReviewSnapshot {
  session_id: string;
  scene_ref: TargetVersionRef;
  target_ref: TargetVersionRef;
  binding_id: string;
  binding_version: number;
  envelope_digest: string;
  core_digest: string;
  frames: [ReviewFrame, ReviewFrame];
  expires_at: string;
}

export interface DeliveredFrame {
  bytes: ArrayBuffer;
  attemptId: string;
  pngDigest: string;
}

export interface PairObservations {
  view_coverage: string | null;
  camera_center: string | null;
  yaw_relation: string | null;
  rejection_reason: string | null;
}

export interface SpatialPreview {
  preview: { base_preview: { preview_id: string; expires_at: string } };
  preview_digest: string;
}

/** The workflow profile; the server pins its provider, model and parameters. */
export const SHOT_PROFILE_REF = "r2-wan27-r2v-two-view@1";

function base(projectName: string): string {
  return `/projects/${encodeURIComponent(projectName)}/m8/spatial`;
}

function post<T>(endpoint: string, body: unknown, options: CallOptions): Promise<T> {
  return API.request(endpoint, { method: "POST", body: JSON.stringify(body), signal: options.signal });
}

export function listShotTargets(projectName: string, options: CallOptions = {}): Promise<ShotTargetState[]> {
  return API.request(`${base(projectName)}/targets`, { signal: options.signal });
}

/** Binding receipts must be distinct and sorted by receipt ID; the server stores which is MASTER at review. */
export function createBinding(
  projectName: string,
  target: TargetVersionRef,
  frames: [FrameRef, FrameRef],
  options: CallOptions = {},
): Promise<{ binding_id: string }> {
  const ordered = [...frames].sort((a, b) => (a.receipt_id < b.receipt_id ? -1 : 1));
  return post(
    `${base(projectName)}/bindings`,
    {
      command_id: `binding:${target.target_id}:${target.registry_version}:${ordered.map((f) => f.receipt_id).join("+")}`,
      expected_target_ref: target,
      ordered_frame_receipts: ordered,
    },
    options,
  );
}

export function openReview(projectName: string, targetId: string, options: CallOptions = {}): Promise<ReviewSnapshot> {
  return post(`${base(projectName)}/review-sessions`, { target_id: targetId }, options);
}

export async function fetchReviewFrame(
  projectName: string,
  sessionId: string,
  role: ReviewRole,
  options: CallOptions = {},
): Promise<DeliveredFrame> {
  const response = await API.requestBinary(
    `${base(projectName)}/review-sessions/${encodeURIComponent(sessionId)}/frames/${role}`,
    { signal: options.signal },
  );
  return {
    bytes: await response.arrayBuffer(),
    attemptId: response.headers.get("X-Review-Attempt-Id") ?? "",
    pngDigest: response.headers.get("X-Review-Png-Digest") ?? "",
  };
}

/** `sha256:<hex>` of the bytes as the browser received them. */
export async function sha256Digest(bytes: ArrayBuffer): Promise<string> {
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return `sha256:${Array.from(hash, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

export function acknowledgeFrame(
  projectName: string,
  sessionId: string,
  input: { attemptId: string; role: ReviewRole; pngDigest: string },
  options: CallOptions = {},
): Promise<unknown> {
  return post(
    `${base(projectName)}/review-sessions/${encodeURIComponent(sessionId)}/acknowledgments`,
    { attempt_id: input.attemptId, role: input.role, png_digest: input.pngDigest, decoded: true },
    options,
  );
}

/** The decision repeats exactly what the reviewer was shown, so a change since then is refused. */
export function decidePair(
  projectName: string,
  snapshot: ReviewSnapshot,
  decision: "APPROVE" | "REJECT",
  observations: PairObservations,
  options: CallOptions = {},
): Promise<unknown> {
  return post(
    `${base(projectName)}/pair-decisions`,
    {
      command_id: `pair:${snapshot.session_id}:${decision}`,
      review_session_id: snapshot.session_id,
      expected_scene_ref: snapshot.scene_ref,
      expected_target_ref: snapshot.target_ref,
      binding_id: snapshot.binding_id,
      expected_binding_version: snapshot.binding_version,
      expected_envelope_digest: snapshot.envelope_digest,
      expected_core_digest: snapshot.core_digest,
      views: snapshot.frames.map(({ role, receipt_id, receipt_digest }) => ({ role, receipt_id, receipt_digest })),
      decision,
      observations,
    },
    options,
  );
}

export function previewPromotion(
  projectName: string,
  input: { candidateId: string; revision: number; targetId: string; bindingVersion: number; assertionIds: string[] },
  options: CallOptions = {},
): Promise<SpatialPreview> {
  return post(
    `${base(projectName)}/promotion-previews`,
    {
      command_id: `preview:${input.candidateId}:${input.revision}:${input.bindingVersion}:${input.assertionIds.join("+")}`,
      candidate_id: input.candidateId,
      candidate_revision: input.revision,
      target_id: input.targetId,
      expected_binding_version: input.bindingVersion,
      selected_assertion_ids: input.assertionIds,
    },
    options,
  );
}

export function promote(
  projectName: string,
  preview: SpatialPreview,
  candidateHeadVersion: number,
  options: CallOptions = {},
): Promise<unknown> {
  return post(
    `${base(projectName)}/promotions`,
    {
      command_id: `promote:${preview.preview.base_preview.preview_id}`,
      preview_id: preview.preview.base_preview.preview_id,
      preview_digest: preview.preview_digest,
      expected_candidate_head_version: candidateHeadVersion,
    },
    options,
  );
}

export function approveShot(
  projectName: string,
  targetId: string,
  input: { taskId: string; approvalRecord: string },
  options: CallOptions = {},
): Promise<unknown> {
  return post(
    `/projects/${encodeURIComponent(projectName)}/gates/r2-shots/${encodeURIComponent(targetId)}`,
    { task_id: input.taskId, approval_record: input.approvalRecord },
    options,
  );
}

/** The workflow's spatial candidate for one approved binding version. */
export function workflowCandidateId(targetId: string, bindingVersion: number): string {
  return `shot:${targetId}:b${bindingVersion}`;
}

/** The candidate's head, or null when it was never analyzed (404). */
export async function getCandidateHead(
  projectName: string,
  candidateId: string,
  options: CallOptions = {},
): Promise<CandidateHead | null> {
  try {
    return await API.request<CandidateHead>(
      `/projects/${encodeURIComponent(projectName)}/m8/exploration/candidates/${encodeURIComponent(candidateId)}`,
      { signal: options.signal },
    );
  } catch (error) {
    if (error instanceof ApiRequestError && error.status === 404) return null;
    throw error;
  }
}
