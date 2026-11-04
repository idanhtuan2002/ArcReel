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
  policy: { mode: AutomationMode };
  targets: string[];
  completed_targets: TargetOutput[];
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
