import { useTranslation } from "react-i18next";
import { useLocation } from "wouter";
import { STOPPED, TERMINAL, type RunStage } from "../api/types";
import { showRunControls } from "../runControls";
import { useProjectRuns } from "../runsStore";
import { SEVERITY_TONES } from "@/utils/severity-tone";

/** Stages whose work a hand-made regeneration of an asset, a storyboard, a voice or a clip throws away. */
const MAKING_STAGES: ReadonlySet<RunStage> = new Set(["ASSET_ANALYSIS", "EPISODE_PLAN", "ADAPTATION", "SCRIPT_PLAN", "SCRIPT", "MEDIA"]);
/** Pages where a sheet, a storyboard, a voice, a clip or the source can be regenerated or edited by hand. */
const EDITING_PAGE = /\/app\/projects\/[^/]+\/(characters|scenes|props|products|episodes|source)(\/|$)/;

interface Props {
  projectName: string | null;
}

/**
 * Warns, on the pages where media or the source can be changed by hand, that an automatic run is making its media:
 * regenerating a sheet, a storyboard, a voice or a clip now makes the run redo the work that depends on it. The run's
 * controls stay together on the overview; the notice links there and holds no control of its own. Elsewhere the
 * operations summary and the workspace notifications say what the run is doing.
 */
export function ActiveRunNotice({ projectName }: Props) {
  const { t } = useTranslation("workflow");
  // Read to re-render on navigation; the full address decides whether this page edits media.
  const [, setLocation] = useLocation();
  const runs = useProjectRuns(projectName);
  const run = runs?.[0] ?? null;
  if (
    !projectName ||
    !run ||
    TERMINAL.has(run.status) ||
    STOPPED.has(run.status) ||
    !MAKING_STAGES.has(run.stage) ||
    !EDITING_PAGE.test(window.location.pathname)
  ) {
    return null;
  }
  const episode = Number((run.targets[0] ?? "episode:0").split(":")[1]) || null;

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-[12.5px]"
      style={{ borderBottom: `1px solid ${SEVERITY_TONES.warnings.ring}`, background: SEVERITY_TONES.warnings.soft }}
    >
      <span className="min-w-0 flex-1" style={{ color: "var(--color-text)" }}>
        {t("active_run_notice", { episode, stage: t(`auto_stage_${run.stage}`) })}
      </span>
      <button
        type="button"
        onClick={() => {
          setLocation(`~/app/projects/${encodeURIComponent(projectName)}`);
          showRunControls();
        }}
        className="focus-ring ml-auto rounded-md px-2 py-0.5 text-[11.5px] underline-offset-2 hover:underline"
        style={{ color: "var(--color-text-2)" }}
      >
        {t("active_run_controls")}
      </button>
    </div>
  );
}
