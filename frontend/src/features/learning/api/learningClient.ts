/**
 * The M8-D learning routes: evaluate the cohort comparison rule, list recommendations and record a
 * Human decision. A failed call rejects with `ApiRequestError` carrying the server's message.
 */

import { API } from "@/api";

interface CallOptions {
  signal?: AbortSignal;
}

export type Disposition = "ACCEPT" | "REJECT" | "DEFER" | "REQUEST_EXPERIMENT";
export const DISPOSITIONS: readonly Disposition[] = ["ACCEPT", "REJECT", "DEFER", "REQUEST_EXPERIMENT"];

export interface ArmSummary {
  arm: string | null;
  n: number;
  present: number;
  missing: Record<string, number>;
  mean: string | null;
  median: string | null;
  min: string | null;
  max: string | null;
  observation_ids: string[];
}

export interface Recommendation {
  recommendation_id: string;
  evidence_observation_ids: string[];
  hypothesis: string;
  applicability: Record<string, unknown> & { summaries?: ArmSummary[]; arms?: string[] };
  exclusions: string[];
  confidence: number;
  expected_guardrails: string[];
  expires_at: string;
}

export interface Decision {
  decision_id: string;
  recommendation_id: string;
  disposition: Disposition;
  actor_id: string;
  reason: string;
  governed_proposal_ref: string | null;
  decided_at: string;
}

export interface RecommendationView {
  recommendation: Recommendation;
  recommendation_digest: string;
  language: "causal" | "associative";
  rule: string;
  evidence_cutoff: string;
  created_at: string;
  decisions: Decision[];
  final: boolean;
}

export interface EvaluateRequest {
  source_family: string;
  metric_name: string;
  metric_definition_version: string;
  aggregation: string;
  creative_profile_id: string;
  creative_profile_version: string;
  arm_a: string;
  arm_b: string;
  min_per_arm: number;
  min_relative_lift: string;
  expires_in_days: number;
  command_id: string;
}

export interface EvaluateResponse {
  fired: boolean;
  reason: string;
  relative_lift: string | null;
  evidence_cutoff: string | null;
  arms: ArmSummary[];
  recommendation: RecommendationView | null;
}

function base(projectName: string): string {
  return `/projects/${encodeURIComponent(projectName)}/m8/learning`;
}

export function listRecommendations(projectName: string, options: CallOptions = {}): Promise<RecommendationView[]> {
  return API.request(`${base(projectName)}/recommendations`, { signal: options.signal });
}

export function evaluateRule(
  projectName: string,
  request: EvaluateRequest,
  options: CallOptions = {},
): Promise<EvaluateResponse> {
  return API.request(`${base(projectName)}/recommendations/evaluate`, {
    method: "POST",
    body: JSON.stringify(request),
    signal: options.signal,
  });
}

export function decideRecommendation(
  projectName: string,
  view: RecommendationView,
  disposition: Disposition,
  reason: string,
  commandId: string,
  options: CallOptions = {},
): Promise<Decision> {
  const id = encodeURIComponent(view.recommendation.recommendation_id);
  return API.request(`${base(projectName)}/recommendations/${id}/decisions`, {
    method: "POST",
    body: JSON.stringify({
      disposition,
      expected_recommendation_digest: view.recommendation_digest,
      reason,
      command_id: commandId,
    }),
    signal: options.signal,
  });
}

/** The signed relative lift of arm B over arm A, from the two recorded means; null without both. */
export function relativeLift(arms: ArmSummary[]): number | null {
  const [a, b] = arms;
  if (!a || !b || a.mean === null || b.mean === null) return null;
  const baseline = Number(a.mean);
  return baseline === 0 ? null : (Number(b.mean) - baseline) / Math.abs(baseline);
}
