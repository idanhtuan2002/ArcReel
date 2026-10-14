/**
 * The M8-E format projection routes: sources, profiles, plans, renders, technical checks, blind review,
 * candidates, previews and promotion approval. A failed call rejects with `ApiRequestError`.
 */

import { API } from "@/api";

interface CallOptions {
  signal?: AbortSignal;
}

export type ReframeKind = "PAD" | "COVER_CENTER" | "COVER_FOCAL";
export type Verdict = "PASS" | "FAIL";

export interface BoxBody {
  x0: string;
  y0: string;
  x1: string;
  y1: string;
}

export interface FormatSource {
  artifact_key: string;
  label: string;
  master_version: number;
  content_digest: string;
}

export interface OutputProfile {
  profile_ref: string;
  platform: string;
  surface: string;
  width: number;
  height: number;
  fps: string;
  duration_limit_seconds: string | null;
  container: string;
  video_codec: string;
  audio_codec: string | null;
  source_refs: string[];
  effective_at: string;
}

export interface OverlaySet {
  constraint_ref: string;
  platform: string;
  surface: string;
  locale: string;
  ui_variant: string;
  regions: Record<string, string>[];
  source_refs: string[];
  effective_at: string;
}

export interface ReframeDecision {
  decision_id: string;
  kind: ReframeKind;
  source_span: Record<string, unknown>;
  target_span: Record<string, unknown>;
  rationale: string;
  semantic_risk: "LOW" | "MEDIUM" | "HIGH";
}

export interface FormatPlan {
  plan_id: string;
  source_master_id: string;
  source_master_digest: string;
  output_profile: OutputProfile;
  overlay_constraints: OverlaySet;
  reframe_decisions: ReframeDecision[];
  plan_digest: string;
}

export interface TechnicalCheck {
  name: string;
  observed: unknown;
  expected: unknown;
  verdict: Verdict;
}

export interface TechnicalReport {
  report_id: string;
  artifact_digest: string;
  checks: TechnicalCheck[];
  passed: boolean;
}

export interface SemanticReport {
  report_id: string;
  artifact_digest: string;
  reviews: { reviewer_id: string; items: Record<string, Verdict> }[];
  material_disagreement: boolean;
  passed: boolean;
}

export interface RenderView {
  execution_id: string;
  plan_id: string;
  artifact_digest: string;
  replayed: boolean;
}

export interface PlanSummary {
  plan: FormatPlan;
  renders: RenderView[];
  technical: TechnicalReport | null;
  semantic: SemanticReport | null;
}

export interface ReviewPacket {
  packet_id: string;
  rubric_version: string;
  items: string[];
}

export interface PreparedCandidate {
  candidate_id: string;
  revision: number;
  head_version: number;
  slot_key: string;
  expected_target_version: number;
}

export interface FormatPreview {
  preview: { preview_id: string; expires_at: string; impact: Record<string, unknown> };
  preview_digest: string;
}

export interface PromotionReceipt {
  receipt_id: string;
  result_artifact_ref: string;
  result_digest: string;
  promoted_at: string;
}

export interface CreatePlanRequest {
  plan_id: string;
  source_artifact_key: string;
  profile_ref: string;
  constraint_ref: string;
  kind: ReframeKind;
  focal: BoxBody | null;
  subject: BoxBody;
  captions: BoxBody[];
  rationale: string;
}

function base(projectName: string): string {
  return `/projects/${encodeURIComponent(projectName)}/m8/formats`;
}

function post<T>(endpoint: string, body: unknown, options: CallOptions = {}): Promise<T> {
  return API.request(endpoint, { method: "POST", body: JSON.stringify(body), signal: options.signal });
}

/** Three governed V1 projections of a generic feed with no platform UI overlay. */
const EFFECTIVE_AT = "2026-10-14T00:00:00Z";
export const STANDARD_PROFILES: OutputProfile[] = [
  [1920, 1080, "landscape-16x9@1"],
  [1080, 1920, "vertical-9x16@1"],
  [1080, 1080, "square-1x1@1"],
].map(([width, height, ref]) => ({
  profile_ref: String(ref),
  platform: "generic",
  surface: "feed",
  width: Number(width),
  height: Number(height),
  fps: "30",
  duration_limit_seconds: null,
  container: "mp4",
  video_codec: "h264",
  audio_codec: "aac",
  source_refs: ["arcreel-standard-profiles-2026-10"],
  effective_at: EFFECTIVE_AT,
}));
export const NO_OVERLAY: OverlaySet = {
  constraint_ref: "generic-feed-none@1",
  platform: "generic",
  surface: "feed",
  locale: "und",
  ui_variant: "none",
  regions: [],
  source_refs: ["arcreel-standard-profiles-2026-10"],
  effective_at: EFFECTIVE_AT,
};

export function listSources(projectName: string, options: CallOptions = {}): Promise<FormatSource[]> {
  return API.request(`${base(projectName)}/sources`, { signal: options.signal });
}

export function listPlans(projectName: string, options: CallOptions = {}): Promise<PlanSummary[]> {
  return API.request(`${base(projectName)}/plans`, { signal: options.signal });
}

export async function ensureStandardProfiles(projectName: string, options: CallOptions = {}): Promise<void> {
  for (const profile of STANDARD_PROFILES) {
    await post(`${base(projectName)}/profiles`, profile, options);
  }
  await post(`${base(projectName)}/overlays`, NO_OVERLAY, options);
}

export function createPlan(projectName: string, request: CreatePlanRequest, options: CallOptions = {}): Promise<FormatPlan> {
  return post(`${base(projectName)}/plans`, request, options);
}

export function renderPlan(projectName: string, planId: string, commandId: string, options: CallOptions = {}): Promise<RenderView> {
  return post(`${base(projectName)}/plans/${encodeURIComponent(planId)}/renders`, { command_id: commandId }, options);
}

export function validateRender(projectName: string, executionId: string, options: CallOptions = {}): Promise<TechnicalReport> {
  return post(`${base(projectName)}/renders/${encodeURIComponent(executionId)}/validation`, {}, options);
}

export function openReview(projectName: string, executionId: string, options: CallOptions = {}): Promise<ReviewPacket> {
  return post(`${base(projectName)}/renders/${encodeURIComponent(executionId)}/review-packets`, {}, options);
}

/** One blind clip as an object URL; the caller revokes it. */
export async function reviewClip(
  projectName: string,
  packetId: string,
  label: "A" | "B",
  options: CallOptions = {},
): Promise<string> {
  const response = await API.requestBinary(
    `${base(projectName)}/review-packets/${encodeURIComponent(packetId)}/clips/${label}`,
    { signal: options.signal },
  );
  return URL.createObjectURL(await response.blob());
}

export function submitReview(
  projectName: string,
  packetId: string,
  items: Record<string, Verdict>,
  note: string,
  options: CallOptions = {},
): Promise<SemanticReport> {
  return post(`${base(projectName)}/review-packets/${encodeURIComponent(packetId)}/reviews`, { items, note }, options);
}

export function prepareCandidate(projectName: string, executionId: string, options: CallOptions = {}): Promise<PreparedCandidate> {
  return post(`${base(projectName)}/renders/${encodeURIComponent(executionId)}/candidate`, {}, options);
}

export function previewPromotion(
  projectName: string,
  candidate: PreparedCandidate,
  commandId: string,
  options: CallOptions = {},
): Promise<FormatPreview> {
  return post(
    `${base(projectName)}/previews`,
    {
      candidate_id: candidate.candidate_id,
      revision: candidate.revision,
      slot_key: candidate.slot_key,
      expected_target_version: candidate.expected_target_version,
      command_id: commandId,
    },
    options,
  );
}

export function approvePromotion(
  projectName: string,
  preview: FormatPreview,
  headVersion: number,
  commandId: string,
  options: CallOptions = {},
): Promise<PromotionReceipt> {
  return post(
    `${base(projectName)}/promotions`,
    {
      preview_id: preview.preview.preview_id,
      preview_digest: preview.preview_digest,
      expected_candidate_head_version: headVersion,
      command_id: commandId,
    },
    options,
  );
}

/** A box written as fractions from four 0..1 numbers (UI percentages divided by 100). */
export function boxFromPercent(x0: number, y0: number, x1: number, y1: number): BoxBody {
  const fraction = (value: number) => `${Math.round(value * 100)}/10000`;
  return { x0: fraction(x0), y0: fraction(y0), x1: fraction(x1), y1: fraction(y1) };
}

/** A box's numeric value (fractions like "2/5" or "175/512"). */
export function boxValue(box: Record<string, unknown>): { x0: number; y0: number; x1: number; y1: number } {
  const read = (key: string) => {
    const [numerator, denominator] = String(box[key]).split("/").map(Number);
    return denominator ? numerator / denominator : numerator;
  };
  return { x0: read("x0"), y0: read("y0"), x1: read("x1"), y1: read("y1") };
}
