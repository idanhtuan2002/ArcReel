/** Wire shapes of the production run API; identity and authority fields are server-derived, never sent. */

export type AutomationMode = "auto" | "semi";

export type RunStatus =
  | "PENDING"
  | "RUNNING"
  | "WAITING_TASK"
  | "WAITING_REVIEW"
  | "PAUSED"
  | "BLOCKED_INPUT_CHANGED"
  | "BLOCKED_CONFIGURATION"
  | "BLOCKED_BUDGET"
  | "BLOCKED_RESOURCE"
  | "BLOCKED_UNKNOWN"
  | "FAILED_QUALITY"
  | "FAILED"
  | "CANCELLING"
  | "CANCELLED"
  | "SUCCEEDED";

export type RunStage =
  | "BRIEF"
  | "STORY"
  | "STORY_COMMIT"
  | "HANDOFF"
  | "ASSET_ANALYSIS"
  | "EPISODE_PLAN"
  | "SCRIPT_PLAN"
  | "SCRIPT"
  | "MEDIA"
  | "RENDER"
  | "MASTER"
  | "QUALITY"
  | "PACKAGE"
  | "EXPORT";

/** The run's stages in order; the stage list in the panel follows it. */
export const STAGES: readonly RunStage[] = [
  "BRIEF",
  "STORY",
  "STORY_COMMIT",
  "HANDOFF",
  "ASSET_ANALYSIS",
  "EPISODE_PLAN",
  "SCRIPT_PLAN",
  "SCRIPT",
  "MEDIA",
  "RENDER",
  "MASTER",
  "QUALITY",
  "PACKAGE",
  "EXPORT",
];

export type Checkpoint = "STORY_MANUSCRIPT" | "SCRIPT_PACKAGE" | "FINAL_FILM";

export interface PendingReview {
  checkpoint: Checkpoint;
  binding_digest: string;
}

/** PASS, or REWORK when a recording quality gate exported the best version the reviewers rejected. */
export type QualityDecision = "PASS" | "REWORK";

export interface TargetOutput {
  target: string;
  archive_digest: string;
  archive_size: number;
  final_digest: string;
  quality_decision: QualityDecision;
}

export interface RunSnapshot {
  user_id: string;
  project_name: string;
  run_id: string;
  status: RunStatus;
  stage: RunStage;
  generation: number;
  version: number;
  input_digest: string;
  policy_digest: string;
  mode_policy_digests: Record<AutomationMode, string>;
  policy: { mode: AutomationMode; final_evaluation_limit?: number };
  targets: string[];
  completed_targets: TargetOutput[];
  repair_counts?: { stage: RunStage; unit_key: string; count: number }[];
  final_evaluations?: number;
  pending_review: PendingReview | null;
  reason: string | null;
  created_at: string;
}

export interface StartOffer {
  enabled: boolean;
  reason?: string;
  input_digest?: string;
  policy_digests?: Record<AutomationMode, string>;
  /** Episodes one run of this project may produce (1 unless the project's settings allow more). */
  max_target_episodes?: number;
}

export interface RunList {
  start: StartOffer;
  runs: RunSnapshot[];
}

export const TERMINAL: ReadonlySet<RunStatus> = new Set(["SUCCEEDED", "FAILED", "FAILED_QUALITY", "CANCELLED"]);
export const STOPPED: ReadonlySet<RunStatus> = new Set([
  "PAUSED",
  "BLOCKED_INPUT_CHANGED",
  "BLOCKED_CONFIGURATION",
  "BLOCKED_BUDGET",
  "BLOCKED_RESOURCE",
  "BLOCKED_UNKNOWN",
]);

export type ReviewScore = "story" | "visual" | "audio" | "continuity" | "pacing";

export interface ReviewFinding {
  code: string;
  severity: string;
  detail: string;
}

export interface TargetReview {
  role: string;
  model_identity: string;
  outcome: string;
  accepted: boolean;
  scores: Partial<Record<ReviewScore, number>>;
  findings: ReviewFinding[];
}

export interface StoryException {
  code: string;
  severity: string;
  node_id: string;
  message: string;
  quote: string;
}

/** What the run decided on its own: reviewer verdicts per target and the story exceptions it accepted. */
export interface RunReport {
  run_id: string;
  quality: { target: string; reviews: TargetReview[] }[];
  story_exceptions: StoryException[];
}

export interface ReadinessRoute {
  role: string;
  provider_id: string;
  model_id: string;
  model_identity: string;
  local: boolean;
  paid: boolean;
  max_cost_per_call: number | null;
}

/** Whether a Start would pass preflight now, with its reasons and the policy it would freeze. */
export interface Readiness {
  ready: boolean;
  reasons: string[];
  launch_profile_id?: string;
  quality_gate?: "enforce" | "record";
  local_only?: boolean;
  routes: ReadinessRoute[];
  limits: {
    currency: string;
    max_cost_minor_units: number;
    max_model_calls: number;
    max_tasks: number;
    max_runtime_seconds: number;
    max_target_episodes: number;
  } | null;
}

export type AutomationRole = "writer" | "script" | "reviewer_a" | "reviewer_b" | "image" | "video" | "audio";

export interface RouteSetting {
  role: AutomationRole;
  provider_id: string;
  model_id: string;
  max_cost_per_call?: number | null;
}

export interface AutomationSettingsView {
  configured: boolean;
  has_quality_profile: boolean;
  profile_id?: string | null;
  launch_profile_id: string;
  routes: RouteSetting[];
  currency?: string;
  max_cost_minor_units?: number;
  max_model_calls?: number;
  max_runtime_seconds?: number;
  max_target_episodes?: number;
}

export interface ModelOption {
  provider_id: string;
  model_id: string;
  label: string;
  local: boolean;
}

export interface PublishedProfile {
  profile_id: string;
  revision: number;
  profile_digest: string;
  /** Every slot is a model slot: the profile an automatic run can use. */
  automatic: boolean;
}

export interface AutomationSettings {
  settings: AutomationSettingsView;
  options: Record<AutomationRole, ModelOption[]>;
  launch_profiles: string[];
  quality_profiles: PublishedProfile[];
}

export interface AutomationSettingsUpdate {
  profile_id?: string | null;
  launch_profile_id: string;
  routes: RouteSetting[];
  currency: string;
  max_cost_minor_units: number;
  max_model_calls: number;
  max_runtime_seconds: number;
  max_target_episodes: number;
}

export interface ReviewerJob {
  role: string;
  model_identity: string;
  state: "running" | "done" | "failed";
  done: number;
  total: number;
  qualified: boolean | null;
  error: string | null;
  started_at: string;
}

/** Whether each reviewer route and the launch are qualified, and reviewer jobs running on this host. */
export interface QualificationStatus {
  corpus_configured: boolean;
  evidence_configured: boolean;
  reviewers: { role: string; model_identity: string; qualified: boolean; job: ReviewerJob | null }[];
  launch_recorded: boolean;
}
