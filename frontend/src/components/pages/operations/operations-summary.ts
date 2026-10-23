import { pendingDecisions } from "@/components/canvas/pipeline/pipeline-stages";
import { stageForPhase, type NorthStarStage } from "@/components/layout/PhaseStepper";
import { WORKING_PHASES, type RunSummary } from "@/features/story-authoring/api/storyClient";
import type { ProjectSummary } from "@/types/project";
import type { TaskItem } from "@/types/task";

export interface OperationsSummary {
  decisions: { project: string; title: string; runId: string; idea: string }[];
  running: { project: string; title: string; storyRuns: number; tasks: number }[];
  stages: { project: string; title: string; stage: NorthStarStage | null }[];
}

/**
 * 跨项目的运营总览：等待人工的决定、进行中的工作、各项目所处的北极星阶段。只读汇总各项目
 * 现有服务端数据（故事运行、任务队列、项目阶段），不调度、不判定，入口指向各自的归属界面。
 */
export function summarizeOperations(
  projects: ProjectSummary[],
  runsByProject: Record<string, RunSummary[]>,
  activeTasks: TaskItem[],
): OperationsSummary {
  const decisions: OperationsSummary["decisions"] = [];
  const running: OperationsSummary["running"] = [];
  for (const project of projects) {
    const runs = runsByProject[project.name] ?? [];
    for (const run of pendingDecisions(runs)) {
      decisions.push({ project: project.name, title: project.title, runId: run.run_id, idea: run.idea });
    }
    const storyRuns = runs.filter((run) => WORKING_PHASES.has(run.phase)).length;
    const tasks = activeTasks.filter((task) => task.project_name === project.name).length;
    if (storyRuns > 0 || tasks > 0) running.push({ project: project.name, title: project.title, storyRuns, tasks });
  }
  const stages = projects.map((project) => ({
    project: project.name,
    title: project.title,
    stage: stageForPhase("phase" in project.status ? (project.status.phase as string | undefined) : undefined),
  }));
  return { decisions, running, stages };
}
