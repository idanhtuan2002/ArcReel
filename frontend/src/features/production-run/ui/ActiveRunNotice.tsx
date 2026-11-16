import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { controlProductionRun, listProductionRuns, newCommandId } from "../api/productionRunClient";
import { STOPPED, TERMINAL, type RunSnapshot, type RunStage } from "../api/types";
import { SEVERITY_TONES } from "@/utils/severity-tone";

const REFRESH_MS = 20000;
/** Stages whose work a hand-made regeneration of an asset, a storyboard, a voice or a clip throws away. */
const MAKING_STAGES: ReadonlySet<RunStage> = new Set(["ASSET_ANALYSIS", "EPISODE_PLAN", "ADAPTATION", "SCRIPT_PLAN", "SCRIPT", "MEDIA"]);

interface Props {
  projectName: string | null;
}

/**
 * Says, on every page of a project, that an automatic run is making its media: regenerating a sheet, a storyboard, a
 * voice or a clip by hand now makes the run redo the work that depends on it. Offers to pause the run first.
 */
export function ActiveRunNotice({ projectName }: Props) {
  const { t } = useTranslation("workflow");
  // The latest run with the project it was read for: a run read for another project is never shown.
  const [read, setRead] = useState<{ project: string; run: RunSnapshot | null } | null>(null);
  const [pausing, setPausing] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!projectName) return;
    let controller = new AbortController();
    const load = () => {
      controller.abort();
      controller = new AbortController();
      const { signal } = controller;
      listProductionRuns(projectName, { signal })
        .then((list) => {
          if (!signal.aborted) setRead({ project: projectName, run: list.runs[0] ?? null });
        })
        .catch(() => {
          // A notice, not a source of truth: without the run list nothing is shown.
        });
    };
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [projectName]);

  const run = read && read.project === projectName ? read.run : null;
  if (!projectName || !run || TERMINAL.has(run.status) || STOPPED.has(run.status) || !MAKING_STAGES.has(run.stage)) {
    return null;
  }
  const episode = Number((run.targets[0] ?? "episode:0").split(":")[1]) || null;

  const pause = async () => {
    setPausing(true);
    setFailed(false);
    try {
      const paused = await controlProductionRun(projectName, run.run_id, "pause", {
        command_id: newCommandId(),
        expected_version: run.version,
        expected_input_digest: run.input_digest,
        policy_digest: run.policy_digest,
      });
      setRead({ project: projectName, run: paused });
    } catch {
      setFailed(true);
    } finally {
      setPausing(false);
    }
  };

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-[12.5px]"
      style={{ borderBottom: `1px solid ${SEVERITY_TONES.warnings.ring}`, background: SEVERITY_TONES.warnings.soft }}
    >
      <span style={{ color: "var(--color-text)" }}>
        {t("active_run_notice", { episode, stage: t(`auto_stage_${run.stage}`) })}
      </span>
      <button
        type="button"
        disabled={pausing}
        onClick={() => void pause()}
        className="focus-ring rounded-md px-2 py-0.5 disabled:opacity-50"
        style={{ border: `1px solid ${SEVERITY_TONES.warnings.ring}`, color: "var(--color-text)" }}
      >
        {t("active_run_pause")}
      </button>
      {failed && <span style={{ color: SEVERITY_TONES.blocking.color }}>{t("active_run_pause_failed")}</span>}
    </div>
  );
}
