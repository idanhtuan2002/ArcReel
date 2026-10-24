/**
 * The story run routes: draft a brief for Gate A, start a run, read it, touchpoint 2 (approve, revise,
 * discard), the run lifecycle, export and the hand-off to video. A failed call rejects with `ApiRequestError`.
 */

import { API } from "@/api";

interface CallOptions {
  signal?: AbortSignal;
}

export type RunPhase =
  | "RUNNING"
  | "AWAITING_GATE_A"
  | "READY_FOR_APPROVAL"
  | "APPROVING"
  | "PARTIALLY_COMMITTED"
  | "COMMIT_BLOCKED"
  | "COMMITTED"
  | "WITHDRAWN"
  | "DISCARDED"
  | "ABORTED_PARTIAL"
  | "BLOCKED_BUDGET"
  | "BLOCKED_QUALITY"
  | "BLOCKED_BINDING_MISMATCH"
  | "BLOCKED_PROPAGATION"
  | "MODEL_UNAVAILABLE"
  | "RECOVERY_INCONSISTENT";

export const BLOCKED_PHASES: ReadonlySet<RunPhase> = new Set([
  "BLOCKED_BUDGET",
  "BLOCKED_QUALITY",
  "BLOCKED_BINDING_MISMATCH",
  "BLOCKED_PROPAGATION",
  "MODEL_UNAVAILABLE",
]);
/** Phases the server is still working in; the page polls while a run is in one of them. */
export const WORKING_PHASES: ReadonlySet<RunPhase> = new Set(["RUNNING", "APPROVING"]);

export type Severity = "HARD_INTEGRITY" | "HARD_STRUCTURAL" | "NARRATIVE_CRITICAL" | "LOCAL_MODEL_LIMIT" | "STYLISTIC";

export interface Finding {
  code: string;
  severity: Severity;
  node_id: string;
  message: string;
  quote: string;
  id?: string;
}

export interface ModelSelection {
  provider_id: string;
  model_id: string;
  endpoint: string;
  base_url: string;
  has_credential: boolean;
  digest: string;
}

export interface StoryBrief {
  idea: string;
  genre: string;
  selection: ModelSelection;
  judge_selection: ModelSelection | null;
  story_target_syllables: number;
  limits?: { currency: string; max_cost_minor_units: number };
  [key: string]: unknown;
}

export interface Packaging {
  titles: { title: string; kind: string }[];
  blurbs: string[];
  selling_points: { point: string; evidence_quote: string }[];
  tags: string[];
}

export interface OfferedScene {
  node_id: string;
  chapter: number;
  scene: number;
  text: string;
}

export interface Offered {
  manifest_digest: string;
  export_digest: string;
  scenes: OfferedScene[];
  findings: Finding[];
  packaging: Packaging | null;
  exceptions_offered: string[];
  completed_steps: string[];
  blocked_step: string | null;
}

export interface Usage {
  count_calls: number;
  generate_calls: number;
  input_tokens: number;
  output_tokens: number;
  model_milliseconds: number;
}

export interface Handoff {
  command_id: string;
  filename: string;
  export_digest: string;
  /** False while a hand-off is recorded but its upload has not completed; only its command may finish it. */
  done: boolean;
  path: string | null;
}

export interface StoryRun {
  run_id: string;
  phase: RunPhase;
  block_reason: string | null;
  blocked_findings: Finding[];
  brief: StoryBrief;
  brief_digest: string;
  usage: Usage;
  limits: { input_tokens_max: number; output_tokens_max: number; wall_clock_max_seconds: number };
  intents: Record<string, string[]>;
  offered: Offered | null;
  handoff: Handoff | null;
}

export interface RunSummary {
  run_id: string;
  phase: RunPhase;
  idea: string;
  genre: string;
  started_at: string;
}

export interface DraftBriefRequest {
  idea: string;
  genre: string;
  provider_id: string;
  model_id: string;
  story_target_syllables: number;
  judge_provider_id: string | null;
  judge_model_id: string | null;
  max_cost_minor_units?: number;
}

export interface DraftedBrief {
  brief: StoryBrief;
  brief_digest: string;
}

export type LifecycleAction = "resume" | "abort" | "retry" | "discard" | "withdraw";
export type OnConflict = "fail" | "replace" | "rename";

/** Backend-owned story choices; display metadata does not authorize dispatch. */
export interface StoryRoute {
  provider_id: string;
  model_id: string;
  label: string;
  enabled: boolean;
  reason: "MISSING_CREDENTIAL" | "NOT_QUALIFIED" | "UNAVAILABLE" | null;
  cloud: boolean;
}

function base(projectName: string): string {
  return `/projects/${encodeURIComponent(projectName)}/story-runs`;
}

function post<T>(endpoint: string, body: unknown, options: CallOptions = {}): Promise<T> {
  return API.request(endpoint, { method: "POST", body: JSON.stringify(body), signal: options.signal });
}

export async function listRoutes(options: CallOptions = {}): Promise<StoryRoute[]> {
  const { routes } = await API.request<{ routes: StoryRoute[] }>("/system/config/story-routes", {
    signal: options.signal,
  });
  return routes;
}

export async function listRuns(projectName: string, options: CallOptions = {}): Promise<RunSummary[]> {
  const { runs } = await API.request<{ runs: RunSummary[] }>(base(projectName), { signal: options.signal });
  return runs;
}

export function getRun(projectName: string, runId: string, options: CallOptions = {}): Promise<StoryRun> {
  return API.request(`${base(projectName)}/${encodeURIComponent(runId)}`, { signal: options.signal });
}

export function draftBrief(
  projectName: string,
  request: DraftBriefRequest,
  options: CallOptions = {},
): Promise<DraftedBrief> {
  return post(`${base(projectName)}/brief`, request, options);
}

/** Gate A: the Human greenlights the exact brief digest; the run then starts under that decision. */
export async function greenlightAndStart(
  projectName: string,
  drafted: DraftedBrief,
  options: CallOptions = {},
): Promise<string> {
  const decision = await API.greenlightProject(projectName, {
    source_digest: drafted.brief_digest,
    action: "GREENLIGHT",
  });
  const started = await post<{ run_id: string }>(
    base(projectName),
    { brief: drafted.brief, gate_a_decision_id: decision.decision_id },
    options,
  );
  return started.run_id;
}

export function approveRun(
  projectName: string,
  runId: string,
  manifestDigest: string,
  acceptedExceptions: string[],
  options: CallOptions = {},
): Promise<StoryRun> {
  return post(
    `${base(projectName)}/${encodeURIComponent(runId)}/approve`,
    { manifest_digest: manifestDigest, accepted_exceptions: acceptedExceptions },
    options,
  );
}

export function reviseRun(
  projectName: string,
  runId: string,
  target: string,
  note: string,
  options: CallOptions = {},
): Promise<StoryRun> {
  return post(`${base(projectName)}/${encodeURIComponent(runId)}/revise`, { target, note }, options);
}

export function runAction(
  projectName: string,
  runId: string,
  action: LifecycleAction,
  options: CallOptions = {},
): Promise<StoryRun> {
  return post(`${base(projectName)}/${encodeURIComponent(runId)}/${action}`, {}, options);
}

export async function exportRun(projectName: string, runId: string, options: CallOptions = {}): Promise<Blob> {
  const response = await API.requestBinary(`${base(projectName)}/${encodeURIComponent(runId)}/export`, {
    signal: options.signal,
  });
  return response.blob();
}

export function sendToVideo(
  projectName: string,
  runId: string,
  commandId: string,
  onConflict: OnConflict,
  options: CallOptions = {},
): Promise<Handoff> {
  return post(
    `${base(projectName)}/${encodeURIComponent(runId)}/send-to-video`,
    { command_id: commandId, on_conflict: onConflict },
    options,
  );
}
