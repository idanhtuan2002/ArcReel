import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "wouter";
import { listProductionRuns } from "../api/productionRunClient";
import { STOPPED, TERMINAL, type RunSnapshot, type RunStage } from "../api/types";
import { SEVERITY_TONES } from "@/utils/severity-tone";
import { RUN_CONTROLS_ID } from "./ProjectOutcome";

const REFRESH_MS = 20000;
/** Stages whose work a hand-made regeneration of an asset, a storyboard, a voice or a clip throws away. */
const MAKING_STAGES: ReadonlySet<RunStage> = new Set(["ASSET_ANALYSIS", "EPISODE_PLAN", "ADAPTATION", "SCRIPT_PLAN", "SCRIPT", "MEDIA"]);

interface Props {
  projectName: string | null;
}

/**
 * Says, on every page of a project, that an automatic run is making its media: regenerating a sheet, a storyboard, a
 * voice or a clip by hand now makes the run redo the work that depends on it. The run's controls (pause, resume) stay
 * together on the overview's status card; the notice links there and holds no control of its own.
 */
/** Brings the overview's status card into view and focus once it is on the page (the overview may still be mounting
 * after the navigation; on the overview itself the address does not change, so scrolling is the only response). */
function showRunControls(tries = 30): void {
  const card = document.getElementById(RUN_CONTROLS_ID);
  if (card) {
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.focus({ preventScroll: true });
    return;
  }
  if (tries > 0) window.setTimeout(() => showRunControls(tries - 1), 50);
}

export function ActiveRunNotice({ projectName }: Props) {
  const { t } = useTranslation("workflow");
  const [, setLocation] = useLocation();
  // The latest run with the project it was read for: a run read for another project is never shown.
  const [read, setRead] = useState<{ project: string; run: RunSnapshot | null } | null>(null);

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
