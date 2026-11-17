import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, Play } from "lucide-react";
import {
  downloadProductionOutput,
  resumeProductionRun,
  newCommandId,
  previewProductionFinal,
} from "../api/productionRunClient";
import { STOPPED, TERMINAL, type RunSnapshot } from "../api/types";
import { describeReason } from "../reasonCopy";
import { SEVERITY_TONES } from "@/utils/severity-tone";
import { useLocation } from "wouter";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { HelpHint } from "@/components/ui/HelpHint";
import { RUN_CONTROLS_ID } from "../runControls";
import { useProjectRuns, useRunsStore } from "../runsStore";

/** Stops a new episode plan from the stopped episode on can fix. */
const PLAN_CODES = new Set(["ADAPTATION_FAILED", "ADAPTATION_INPUT_MISSING"]);
/** Stops the project's model choices can fix. */
const MODEL_CODES = (code: string) =>
  code === "ADAPTATION_FAILED" || code === "VOICE_CAST_FAILED" || code.startsWith("MEDIA_") || code.startsWith("PROJECT_");
/** Stops the task list explains. */
const TASK_CODES = new Set(["RESOURCE_UNAVAILABLE", "OUTCOME_UNKNOWN", "OWNER_TASK_FAILED", "RENDER_FAILED"]);

interface FinishedFilm {
  episode: number;
  runId: string;
  passed: boolean;
}

interface Props {
  projectName: string;
  /** Episode titles by number, as the plan names them. */
  titles: Record<number, string>;
  /** Opens the operations details, where a stopped run is resumed or cancelled. */
  onOpenDetails: () => void;
}

/** The newest finished film of each episode, from the runs newest first. */
function finishedFilms(runs: RunSnapshot[]): FinishedFilm[] {
  const seen = new Map<number, FinishedFilm>();
  for (const run of runs) {
    for (const output of run.completed_targets ?? []) {
      const episode = Number(output.target.split(":")[1]);
      if (!Number.isFinite(episode) || seen.has(episode)) continue;
      seen.set(episode, { episode, runId: run.run_id, passed: output.quality_decision === "PASS" });
    }
  }
  return [...seen.values()].sort((a, b) => a.episode - b.episode);
}

/**
 * What a filmmaker looks for first: the films that are finished, to watch or download, and one sentence on where the
 * automatic production stands, with what to do when it stopped. The machinery (stages, gates, attempts) stays in the
 * operations details.
 */
export function ProjectOutcome({ projectName, titles, onOpenDetails }: Props) {
  const { t } = useTranslation("workflow");
  const runs = useProjectRuns(projectName);
  const putRun = useRunsStore((state) => state.putRun);
  const [playing, setPlaying] = useState<Record<string, string>>({});
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionFailed, setActionFailed] = useState(false);
  // Episodes a plan reset from the stopped episode would clear although they have scripts or media: asked first.
  const [consumed, setConsumed] = useState<number[] | null>(null);
  const [, setLocation] = useLocation();
  const setTaskHudOpen = useAppStore((s) => s.setTaskHudOpen);
  const refreshProject = useProjectsStore((s) => s.refreshProject);
  const urls = useRef<string[]>([]);
  useEffect(() => () => urls.current.forEach((url) => URL.revokeObjectURL(url)), []);


  if (runs === null || runs.length === 0) return null;
  const films = finishedFilms(runs);
  const latest = runs[0];
  const episodeOf = (run: RunSnapshot) => Number((run.targets[0] ?? "episode:0").split(":")[1]) || null;
  const latestEpisode = episodeOf(latest);
  const stopped = STOPPED.has(latest.status) || latest.status === "FAILED" || latest.status === "FAILED_QUALITY";
  const running = !TERMINAL.has(latest.status) && !stopped;
  const reason = latest.reason ? describeReason(t, latest.reason) : null;

  const play = async (film: FinishedFilm) => {
    setFailed(false);
    try {
      const blob = await previewProductionFinal(projectName, film.runId, film.episode);
      const url = URL.createObjectURL(blob);
      urls.current.push(url);
      setPlaying((current) => ({ ...current, [`${film.runId}:${film.episode}`]: url }));
    } catch {
      setFailed(true);
    }
  };

  const download = async (film: FinishedFilm) => {
    setFailed(false);
    try {
      const blob = await downloadProductionOutput(projectName, film.runId, film.episode);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${projectName}-episode-${film.episode}.zip`;
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setFailed(true);
    }
  };

  const resume = async () => {
    setBusy(true);
    setActionFailed(false);
    try {
      const resumed = await resumeProductionRun(projectName, latest, newCommandId());
      putRun(projectName, resumed);
    } catch {
      setActionFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const resetPlan = async (from: number) => {
    setBusy(true);
    setActionFailed(false);
    try {
      const result = await API.request<{ confirmation_required: boolean; consumed_episodes: number[] }>(
        `/projects/${encodeURIComponent(projectName)}/episode-planning/reset`,
        { method: "POST", body: JSON.stringify({ from_episode: from, confirm_consumed: consumed !== null }) },
      );
      if (result.confirmation_required) {
        setConsumed(result.consumed_episodes);
        return;
      }
      setConsumed(null);
      await refreshProject(projectName);
    } catch {
      setActionFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const tone = stopped ? SEVERITY_TONES.warnings.color : running ? "var(--color-accent-2)" : "var(--color-text-2)";
  const headline = running
    ? t("outcome_running", { episode: latestEpisode, stage: t(`auto_stage_${latest.stage}`) })
    : stopped
      ? t("outcome_stopped", { episode: latestEpisode, stage: t(`auto_stage_${latest.stage}`) })
      : latest.status === "SUCCEEDED"
        ? t("outcome_done", { episode: latestEpisode })
        : t("outcome_cancelled");

  return (
    <section aria-label={t("outcome_section")} className="space-y-3">
      {films.length > 0 && (
        <div>
          <p
            className="num mb-2 text-[10.5px] font-bold uppercase"
            style={{ color: "var(--color-text-4)", letterSpacing: "1.4px" }}
          >
            Finished films{" "}
            <HelpHint topic={t("outcome_section")}>{t("help_review")}</HelpHint>
          </p>
          <ul className="m-0 flex list-none gap-3 overflow-x-auto p-0 pb-1">
            {films.map((film) => {
              const key = `${film.runId}:${film.episode}`;
              const url = playing[key];
              const title = titles[film.episode];
              return (
                <li
                  key={key}
                  className="flex w-40 shrink-0 flex-col overflow-hidden rounded-xl"
                  style={{ border: "1px solid var(--color-hairline)", background: "var(--color-hairline-soft)" }}
                >
                  <div className="relative aspect-[9/16] w-full" style={{ background: "oklch(0.12 0.008 250)" }}>
                    {url ? (
                      // eslint-disable-next-line jsx-a11y/media-has-caption -- the film has its subtitles burned into the picture
                      <video className="h-full w-full object-cover" controls autoPlay src={url} aria-label={t("outcome_film", { episode: film.episode })} />
                    ) : (
                      <button
                        type="button"
                        onClick={() => void play(film)}
                        className="focus-ring absolute inset-0 grid place-items-center"
                        aria-label={t("outcome_watch", { episode: film.episode })}
                      >
                        <span
                          className="grid h-12 w-12 place-items-center rounded-full"
                          style={{ background: "oklch(1 0 0 / 0.12)", color: "var(--color-text)" }}
                        >
                          <Play className="h-5 w-5" aria-hidden />
                        </span>
                      </button>
                    )}
                  </div>
                  <div className="space-y-1 p-2.5">
                    <p className="m-0 text-[12.5px] font-semibold" style={{ color: "var(--color-text)" }}>
                      {t("outcome_episode", { episode: film.episode })}
                    </p>
                    {title && (
                      <p className="m-0 truncate text-[11.5px]" style={{ color: "var(--color-text-3)" }} title={title}>
                        {title}
                      </p>
                    )}
                    <p className="m-0 text-[11px]" style={{ color: film.passed ? "var(--color-accent-2)" : "var(--color-text-3)" }}>
                      {film.passed ? t("outcome_passed") : t("outcome_not_passed")}
                    </p>
                    <button
                      type="button"
                      onClick={() => void download(film)}
                      className="focus-ring inline-flex items-center gap-1 rounded text-[11.5px] underline underline-offset-2 hover:opacity-80"
                      style={{ color: "var(--color-text-2)" }}
                    >
                      <Download className="h-3 w-3" aria-hidden />
                      {t("outcome_download")}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
          {failed && (
            <p role="alert" className="mt-1 text-[12px]" style={{ color: SEVERITY_TONES.blocking.color }}>
              {t("outcome_failed")}
            </p>
          )}
        </div>
      )}

      {!running && (
      <div
        id={RUN_CONTROLS_ID}
        tabIndex={-1}
        className="rounded-xl px-4 py-3 outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent-soft)]"
        role={stopped ? "status" : undefined}
        style={{ border: `1px solid ${tone}`, background: "var(--color-hairline-soft)" }}
      >
        <p className="m-0 text-[14px] font-semibold" style={{ color: tone }}>
          {headline}
        </p>
        {stopped && reason && (
          <>
            <p className="m-0 mt-1 text-[13px]" style={{ color: "var(--color-text)" }}>
              {reason.text.charAt(0).toLocaleUpperCase() + reason.text.slice(1)}
            </p>
            {reason.hint && (
              <p className="m-0 mt-1 text-[12.5px]" style={{ color: "var(--color-text-2)" }}>
                {reason.hint}
              </p>
            )}
          </>
        )}
        {consumed && (
          <p className="m-0 mt-2 text-[12.5px]" style={{ color: SEVERITY_TONES.warnings.color }}>
            {t("outcome_reset_consumed", { episodes: consumed.join(", ") })}
          </p>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {STOPPED.has(latest.status) && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void resume()}
              className="focus-ring rounded-md px-2.5 py-1 text-[12px] font-semibold disabled:opacity-50"
              style={{ background: "var(--color-accent-dim)", border: "1px solid var(--color-accent-soft)", color: "var(--color-text)" }}
            >
              {t("outcome_resume")}
            </button>
          )}
          {stopped && reason && PLAN_CODES.has(reason.code) && latestEpisode !== null && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void resetPlan(latestEpisode)}
              className="focus-ring rounded-md px-2.5 py-1 text-[12px] disabled:opacity-50"
              style={{ border: "1px solid var(--color-hairline)", color: "var(--color-text)" }}
            >
              {consumed ? t("outcome_reset_confirm") : t("outcome_reset_plan", { episode: latestEpisode })}
            </button>
          )}
          {stopped && reason && MODEL_CODES(reason.code) && (
            <button
              type="button"
              onClick={() => setLocation(`~/app/projects/${encodeURIComponent(projectName)}/settings#models`)}
              className="focus-ring rounded-md px-2.5 py-1 text-[12px]"
              style={{ border: "1px solid var(--color-hairline)", color: "var(--color-text)" }}
            >
              {t("outcome_open_models")}
            </button>
          )}
          {stopped && reason && TASK_CODES.has(reason.code) && (
            <button
              type="button"
              onClick={() => setTaskHudOpen(true)}
              className="focus-ring rounded-md px-2.5 py-1 text-[12px]"
              style={{ border: "1px solid var(--color-hairline)", color: "var(--color-text)" }}
            >
              {t("outcome_open_tasks")}
            </button>
          )}
          <button
            type="button"
            onClick={onOpenDetails}
            className="focus-ring rounded-md px-2.5 py-1 text-[12px]"
            style={{ color: "var(--color-text-2)" }}
          >
            {t("outcome_details")}
          </button>
        </div>
        {actionFailed && (
          <p role="alert" className="m-0 mt-1 text-[12px]" style={{ color: SEVERITY_TONES.blocking.color }}>
            {t("outcome_action_failed")}
          </p>
        )}
      </div>
      )}
    </section>
  );
}
