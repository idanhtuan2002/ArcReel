import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "wouter";

import { NORTH_STAR_STAGES, type NorthStarStage } from "@/components/layout/PhaseStepper";
import { nextStepForAction } from "@/components/workflow/problem-views";
import { listRuns, WORKING_PHASES, type RunSummary } from "@/features/story-authoring/api/storyClient";
import { useWorkflowStore } from "@/stores/workflow-store";
import type { WorkflowPlan } from "@/types/workflow";

import { pendingDecisions, stageStates } from "./pipeline-stages";
import "./pipeline-board.css";

/** 有对应界面的阶段入口（相对项目工作区）。 */
const STAGE_ROUTE: Partial<Record<NorthStarStage, string>> = {
  create: "/story",
  prepare: "/characters",
  learn: "/learning",
};

interface PipelineBoardViewProps {
  plan: WorkflowPlan | null;
  runs: RunSummary[];
}

/** 生产环总览：各阶段状态、下一步、等待你处理的决定与进行中的长任务。纯展示，数据由容器给出。 */
export function PipelineBoardView({ plan, runs }: PipelineBoardViewProps) {
  const { t } = useTranslation("dashboard");
  const states = stageStates(plan, runs);
  const decisions = pendingDecisions(runs);
  const running = runs.filter((run) => WORKING_PHASES.has(run.phase));
  const nextAction = plan && plan.next_action.type !== "none" ? nextStepForAction(t, plan.next_action.type) : null;

  return (
    <section aria-labelledby="pipeline-board-title" className="pipeline-board">
      <div className="pipeline-board-head">
        <h2 id="pipeline-board-title">{t("pipeline_board_title")}</h2>
        {nextAction ? <p className="pipeline-next">{nextAction}</p> : null}
      </div>
      <ol className="pipeline-stages">
        {NORTH_STAR_STAGES.map((stage, index) => {
          const route = STAGE_ROUTE[stage];
          const body = (
            <>
              <span className="pipeline-stage-index">{index + 1}</span>
              <span className="pipeline-stage-name">{t(`pipeline_stage_${stage}`)}</span>
              <span className="pipeline-stage-state">{t(`pipeline_state_${states[stage]}`)}</span>
            </>
          );
          return (
            <li key={stage} data-state={states[stage]}>
              {route && states[stage] !== "soon" ? (
                <Link href={route} className="pipeline-stage">
                  {body}
                </Link>
              ) : (
                <div className="pipeline-stage">{body}</div>
              )}
            </li>
          );
        })}
      </ol>
      <div className="pipeline-lists">
        <div>
          <h3>{t("pipeline_decisions_title")}</h3>
          {decisions.length === 0 ? (
            <p className="pipeline-empty">{t("pipeline_nothing_waiting")}</p>
          ) : (
            <ul>
              {decisions.map((run) => (
                <li key={run.run_id}>
                  <Link href="/story" className="pipeline-item">
                    {t("pipeline_decision_story", { idea: run.idea.slice(0, 90) })}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3>{t("pipeline_running_title")}</h3>
          {running.length === 0 ? (
            <p className="pipeline-empty">{t("pipeline_nothing_running")}</p>
          ) : (
            <ul>
              {running.map((run) => (
                <li key={run.run_id}>
                  <Link href="/story" className="pipeline-item">
                    {t("pipeline_running_story", { idea: run.idea.slice(0, 90) })}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}

/** 容器：取项目级工作流计划与故事运行列表，交给 {@link PipelineBoardView}。 */
export function PipelineBoard({ projectName }: { projectName: string }) {
  const plan = useWorkflowStore((s) => s.plan);
  const planKey = useWorkflowStore((s) => s.planKey);
  const refreshPlan = useWorkflowStore((s) => s.refreshPlan);
  const [runs, setRuns] = useState<RunSummary[]>([]);

  useEffect(() => {
    void refreshPlan(projectName, null);
  }, [projectName, refreshPlan]);

  useEffect(() => {
    const controller = new AbortController();
    listRuns(projectName, { signal: controller.signal }).then(
      (found) => {
        if (!controller.signal.aborted) setRuns(found);
      },
      () => undefined,
    );
    return () => controller.abort();
  }, [projectName]);

  // 计划属于别的目标（例如某一集）时不据此陈述状态
  const ownPlan = planKey === `${projectName}::` ? plan : null;
  return <PipelineBoardView plan={ownPlan} runs={runs} />;
}
