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

export type Checkpoint = "STORY_MANUSCRIPT" | "SCRIPT_PACKAGE" | "FINAL_FILM";

export interface PendingReview {
  checkpoint: Checkpoint;
  binding_digest: string;
}

export interface TargetOutput {
  target: string;
  archive_digest: string;
  archive_size: number;
  final_digest: string;
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
