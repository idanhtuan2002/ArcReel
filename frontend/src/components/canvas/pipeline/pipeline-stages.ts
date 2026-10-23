import { NORTH_STAR_STAGES, type NorthStarStage } from "@/components/layout/PhaseStepper";
import { BLOCKED_PHASES, WORKING_PHASES, type RunSummary } from "@/features/story-authoring/api/storyClient";
import type { WorkflowPlan, WorkflowStepState } from "@/types/workflow";

/** 阶段在总览上的状态：完成 / 进行中 / 需要你处理 / 可以开始 / 未到 / 即将推出。 */
export type StageState = "done" | "active" | "attention" | "ready" | "todo" | "soon";

/** 服务端工作流步骤（lib/workflow_plan.py）所属的北极星阶段。 */
const STEP_STAGE: Record<string, NorthStarStage> = {
  episode_plan: "adapt",
  script_plan_content: "adapt",
  script_plan_review: "adapt",
  final_script: "adapt",
  storyboard: "direct",
  asset_inventory: "prepare",
  asset_sheets: "prepare",
  narration_delivery: "produce",
  video: "produce",
};

const DECISION_PHASES = new Set<RunSummary["phase"]>(["READY_FOR_APPROVAL", "AWAITING_GATE_A"]);

function aggregate(states: WorkflowStepState[]): StageState {
  if (states.length === 0) return "todo";
  if (states.includes("blocked")) return "attention";
  if (states.includes("active")) return "active";
  if (states.every((state) => state === "completed" || state === "skipped")) return "done";
  if (states.includes("ready")) return "ready";
  return "todo";
}

/**
 * 把服务端工作流计划与故事运行汇总到北极星阶段；不按文件存在性推断，只用服务端给出的步骤状态、
 * 源文修订与导出状态。计划尚未取得时，除「创作」外一律视为未到。
 */
export function stageStates(plan: WorkflowPlan | null, runs: RunSummary[]): Record<NorthStarStage, StageState> {
  const byStage = new Map<NorthStarStage, WorkflowStepState[]>();
  for (const step of plan?.steps ?? []) {
    const stage = STEP_STAGE[step.id];
    if (stage) byStage.set(stage, [...(byStage.get(stage) ?? []), step.state]);
  }
  const result = Object.fromEntries(NORTH_STAR_STAGES.map((stage) => [stage, aggregate(byStage.get(stage) ?? [])])) as Record<
    NorthStarStage,
    StageState
  >;
  result.discover = "soon";
  result.research = "soon";
  if (runs.some((run) => WORKING_PHASES.has(run.phase))) result.create = "active";
  else if (pendingDecisions(runs).length > 0) result.create = "attention";
  else result.create = plan?.status.source_revision ? "done" : "ready";
  result.evaluate = result.produce === "done" ? "ready" : "todo";
  result.package = plan?.status.state === "EXPORT_READY" ? "ready" : "todo";
  result.learn = "todo";
  return result;
}

/** 等待人工处理的故事运行：待审阅、待重新批准 brief，或被阻断需要决定下一步。 */
export function pendingDecisions(runs: RunSummary[]): RunSummary[] {
  return runs.filter((run) => DECISION_PHASES.has(run.phase) || BLOCKED_PHASES.has(run.phase));
}
