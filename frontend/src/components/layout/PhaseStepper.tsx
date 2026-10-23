import { useTranslation } from "react-i18next";

/**
 * 北极星生产环（docs/r2/R2_01_FROZEN_ARCHITECTURE.md §2）的阶段，按环上顺序排列。
 * 「发现」「调研」尚无对应界面，以「即将推出」弱化呈现，不可点击、不计入当前阶段。
 */
export const NORTH_STAR_STAGES = [
  "discover",
  "research",
  "create",
  "adapt",
  "direct",
  "prepare",
  "produce",
  "evaluate",
  "package",
  "learn",
] as const;

export type NorthStarStage = (typeof NORTH_STAR_STAGES)[number];

const COMING_SOON = new Set<NorthStarStage>(["discover", "research"]);

/** 服务端项目阶段（status.phase）在北极星环上的位置；未知或缺失时为 null。 */
const STAGE_BY_PHASE: Record<string, NorthStarStage> = {
  preparation: "create",
  script: "adapt",
  production: "produce",
  completed: "package",
};

export function stageForPhase(phase: string | undefined): NorthStarStage | null {
  return phase ? (STAGE_BY_PHASE[phase] ?? null) : null;
}

interface PhaseStepperProps {
  currentPhase: string | undefined;
}

/**
 * 顶栏阶段步进器：北极星环十个阶段的紧凑点阵，当前阶段展开为带序号与名称的胶囊，
 * 其余阶段以点表示（名称见 title 与无障碍名称）；已过阶段用弱化 accent，尚无界面的阶段用虚线点。
 */
export function PhaseStepper({ currentPhase }: PhaseStepperProps) {
  const { t } = useTranslation("dashboard");
  const current = stageForPhase(currentPhase);
  const currentIdx = current ? NORTH_STAR_STAGES.indexOf(current) : -1;

  return (
    <nav aria-label={t("workflow_phases")}>
      <ol className="ns-stepper">
        {NORTH_STAR_STAGES.map((stage, idx) => {
          const soon = COMING_SOON.has(stage);
          const state = soon ? "soon" : idx === currentIdx ? "current" : currentIdx >= 0 && idx < currentIdx ? "done" : "todo";
          const label = t(`pipeline_stage_${stage}`);
          const name = soon ? `${label} · ${t("pipeline_coming_soon")}` : label;
          return (
            <li
              key={stage}
              data-state={state}
              aria-current={state === "current" ? "step" : undefined}
              aria-label={`${idx + 1}. ${name}`}
              title={name}
            >
              <span className="ns-dot" aria-hidden="true">
                {state === "current" ? idx + 1 : null}
              </span>
              {state === "current" ? <span className="ns-label">{label}</span> : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
