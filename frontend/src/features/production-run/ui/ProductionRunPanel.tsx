import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiRequestError } from "@/api";
import {
  changeProductionRunMode,
  controlProductionRun,
  getProductionRunProgress,
  downloadProductionOutput,
  listProductionRuns,
  newCommandId,
  reviewProductionRun,
  startProductionRun,
  type ControlAction,
} from "../api/productionRunClient";
import { SEVERITY_TONES } from "@/utils/severity-tone";
import {
  STAGES,
  STOPPED,
  TERMINAL,
  type AutomationMode,
  type RunProgress,
  type RunSnapshot,
  type RunStatus,
  type StartOffer,
} from "../api/types";
import { AutomationQualification } from "./AutomationQualification";
import { AutomationReadiness } from "./AutomationReadiness";
import { AutomationSettingsEditor } from "./AutomationSettingsEditor";
import { RunMediaStrip } from "./RunMediaStrip";
import { RunReportDetails } from "./RunReportDetails";
import { formatDuration, stageTimes, totalTime } from "./runTimeline";

const POLL_MS = 5000;
const EXAMPLE_IDEAS = ["auto_example_1", "auto_example_2", "auto_example_3"] as const;
type HistoryFilter = "all" | "active" | "done" | "failed";
const FAILED: ReadonlySet<RunStatus> = new Set(["FAILED", "FAILED_QUALITY", "CANCELLED"]);

function inFilter(status: RunStatus, filter: HistoryFilter): boolean {
  if (filter === "active") return !TERMINAL.has(status);
  if (filter === "done") return status === "SUCCEEDED";
  if (filter === "failed") return FAILED.has(status);
  return true;
}

const BUTTON_CLS =
  "focus-ring rounded-md px-2.5 py-1 text-[12px] disabled:opacity-50 hover:opacity-90";
const BUTTON_STYLE = { border: "1px solid var(--color-hairline-strong)", color: "var(--color-text-2)" };
const PRIMARY_STYLE = {
  background: "var(--color-accent-dim)",
  border: "1px solid var(--color-accent-soft)",
  color: "var(--color-accent-2)",
};

function statusTone(status: RunStatus): string {
  if (status === "SUCCEEDED") return "var(--color-accent-2)";
  if (status === "FAILED" || status === "FAILED_QUALITY") return SEVERITY_TONES.blocking.color;
  if (STOPPED.has(status)) return SEVERITY_TONES.warnings.color;
  return "var(--color-text-2)";
}

interface Props {
  projectName: string;
}

/**
 * Start and follow one automatic production run of a project.
 *
 * It renders server snapshots only: the stage, status, block reason and pending checkpoint come from the run, never
 * from files on disk. Default mode is automatic. A response for a project the user has since left is dropped, and a
 * Start is sent once per click with a fresh command id so a lost response retried by the server returns the same run.
 */
export function ProductionRunPanel({ projectName }: Props) {
  const { t } = useTranslation("workflow");
  // A reason code the panel has no words for is shown as the code itself, never dropped.
  const reasonText = useCallback((code: string) => t(`auto_reason_${code}`, { defaultValue: code }), [t]);
  // A refused command names its code and reasons in words; anything else keeps its own message.
  const errorText = useCallback(
    (cause: unknown): string => {
      if (cause instanceof ApiRequestError && cause.code) {
        const detail = cause.detail as { reasons?: unknown } | undefined;
        const reasons = Array.isArray(detail?.reasons) ? detail.reasons.map((r) => reasonText(String(r))) : [];
        const head = t(`auto_error_${cause.code}`, { defaultValue: cause.code });
        return reasons.length ? `${head} (${reasons.join(", ")})` : head;
      }
      return cause instanceof Error ? cause.message : String(cause);
    },
    [reasonText, t],
  );
  const [offer, setOffer] = useState<StartOffer | null>(null);
  // Newest first, as the server lists them; the panel follows the newest unless the user picks an earlier run.
  const [runs, setRuns] = useState<RunSnapshot[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const run = runs.find((item) => item.run_id === selected) ?? runs[0] ?? null;
  const setRun = useCallback(
    (updated: RunSnapshot) =>
      setRuns((current) =>
        current.some((item) => item.run_id === updated.run_id)
          ? current.map((item) => (item.run_id === updated.run_id ? updated : item))
          : [updated, ...current],
      ),
    [],
  );
  const [idea, setIdea] = useState("");
  const [mode, setMode] = useState<AutomationMode>("auto");
  const [episodes, setEpisodes] = useState(1);
  const [historyFilter, setHistoryFilter] = useState<HistoryFilter>("all");
  const [progress, setProgress] = useState<RunProgress | null>(null);
  // The time the progress was read; the current stage's elapsed time counts to it.
  const [readAt, setReadAt] = useState(() => Date.now());
  // Bumped after a settings save so readiness is checked again against the new settings.
  const [setupVersion, setSetupVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The parent keys this panel by project, so a mounted panel serves one project; responses that land after it
  // unmounts (the user switched project) are dropped.
  const mounted = useRef(true);

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const list = await listProductionRuns(projectName, { signal });
        if (signal?.aborted || !mounted.current) return;
        setOffer(list.start);
        setRuns(list.runs.filter((item) => item.project_name === projectName));
      } catch (cause) {
        if (signal?.aborted || !mounted.current) return;
        setError(errorText(cause));
      }
    },
    [errorText, projectName],
  );

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    const first = window.setTimeout(() => void refresh(controller.signal), 0);
    const timer = window.setInterval(() => void refresh(controller.signal), POLL_MS);
    return () => {
      mounted.current = false;
      controller.abort();
      window.clearTimeout(first);
      window.clearInterval(timer);
    };
  }, [refresh]);

  // The run's timeline and the current stage's progress (owner tasks like a queue's running and queued counts, the
  // story's writing inside STORY): read once for a finished run, polled while the run is active.
  const progressRunId = run?.run_id ?? null;
  const progressActive = run !== null && !TERMINAL.has(run.status);
  useEffect(() => {
    if (!progressRunId) return;
    const controller = new AbortController();
    const read = () =>
      getProductionRunProgress(projectName, progressRunId, { signal: controller.signal })
        .then((loaded) => {
          if (controller.signal.aborted) return;
          setProgress(loaded);
          setReadAt(Date.now());
        })
        .catch(() => {
          // Progress is supplementary; the stage and status stay authoritative.
        });
    void read();
    if (!progressActive) return () => controller.abort();
    const timer = window.setInterval(() => void read(), POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [projectName, progressRunId, progressActive]);

  const act = useCallback(
    async (call: () => Promise<RunSnapshot>) => {
      if (busy) return;
      setBusy(true);
      setError(null);
      try {
        const updated = await call();
        if (mounted.current) setRun(updated);
      } catch (cause) {
        if (mounted.current) setError(errorText(cause));
      } finally {
        if (mounted.current) setBusy(false);
      }
    },
    [busy, errorText, setRun],
  );

  const start = () => {
    if (!offer?.input_digest || !offer.policy_digests || !idea.trim()) return;
    const command = {
      command_id: newCommandId(),
      mode,
      idea: idea.trim(),
      targets: Array.from({ length: episodes }, (_, index) => `episode:${index + 1}`),
      expected_input_digest: offer.input_digest,
      policy_digest: offer.policy_digests[mode],
    };
    setSelected(null);
    void act(() => startProductionRun(projectName, command));
  };

  const control = (action: ControlAction) => {
    if (!run) return;
    void act(() =>
      controlProductionRun(projectName, run.run_id, action, {
        command_id: newCommandId(),
        expected_version: run.version,
        expected_input_digest: run.input_digest,
        policy_digest: run.policy_digest,
      }),
    );
  };

  const switchMode = () => {
    if (!run) return;
    const target: AutomationMode = run.policy.mode === "auto" ? "semi" : "auto";
    void act(() =>
      changeProductionRunMode(projectName, run.run_id, {
        command_id: newCommandId(),
        expected_version: run.version,
        expected_input_digest: run.input_digest,
        policy_digest: run.mode_policy_digests[target],
        mode: target,
      }),
    );
  };

  const review = (decision: "APPROVE" | "REJECT") => {
    if (!run?.pending_review) return;
    const pending = run.pending_review;
    void act(() =>
      reviewProductionRun(projectName, run.run_id, {
        command_id: newCommandId(),
        expected_version: run.version,
        checkpoint: pending.checkpoint,
        binding_digest: pending.binding_digest,
        decision,
      }),
    );
  };

  const download = async (episode: number) => {
    if (!run) return;
    let blob: Blob;
    try {
      blob = await downloadProductionOutput(projectName, run.run_id, episode);
    } catch (cause) {
      if (mounted.current) setError(errorText(cause));
      return;
    }
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${projectName}-episode-${episode}.zip`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const latest = runs[0] ?? null;
  const shownRuns = runs.filter((item) => item.run_id === run?.run_id || inFilter(item.status, historyFilter));
  const active = run !== null && !TERMINAL.has(run.status);
  const startable = latest === null || TERMINAL.has(latest.status);
  const reached = run ? STAGES.indexOf(run.stage) : -1;
  const runProgress = run && progress?.run_id === run.run_id ? progress : null;
  const times = run ? stageTimes(runProgress, run.stage, active, readAt) : {};
  const total = totalTime(runProgress, active, readAt);
  const story = active && run?.stage === "STORY" ? runProgress?.story : null;
  return (
    <section
      aria-label={t("auto_title")}
      data-testid="production-run-panel"
      className="space-y-2 rounded-lg px-3 py-2"
      style={{ border: "1px solid var(--color-hairline-strong)" }}
    >
      <h3 className="text-[12.5px] font-medium" style={{ color: "var(--color-text)" }}>
        {t("auto_title")}
      </h3>
      {error && (
        <p role="alert" className="text-[12px]" style={{ color: SEVERITY_TONES.blocking.color }}>
          {t("auto_error", { message: error })}
        </p>
      )}
      {startable && offer && !offer.enabled && (
        <p className="text-[12px]" style={{ color: "var(--color-text-3)" }}>
          {t("auto_unavailable", { reason: reasonText(offer.reason ?? "") })}
        </p>
      )}
      {offer?.enabled && <AutomationReadiness key={setupVersion} projectName={projectName} />}
      {offer?.enabled && (
        <AutomationQualification
          projectName={projectName}
          onChanged={() => setSetupVersion((version) => version + 1)}
        />
      )}
      {offer && (
        <AutomationSettingsEditor
          projectName={projectName}
          onSaved={() => {
            setSetupVersion((version) => version + 1);
            void refresh();
          }}
        />
      )}
      {startable && offer?.enabled && (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            start();
          }}
        >
          <label className="block text-[12px]" style={{ color: "var(--color-text-2)" }}>
            {t("auto_idea_label")}
            <textarea
              className="focus-ring mt-1 block w-full rounded-md px-2 py-1.5 text-[12.5px]"
              style={{ border: "1px solid var(--color-hairline-strong)", background: "transparent" }}
              rows={3}
              value={idea}
              placeholder={t("auto_idea_placeholder")}
              onChange={(event) => setIdea(event.target.value)}
            />
          </label>
          <div className="flex flex-wrap items-center gap-1.5 text-[11.5px]">
            <span style={{ color: "var(--color-text-3)" }}>{t("auto_examples")}</span>
            {EXAMPLE_IDEAS.map((key) => (
              <button
                key={key}
                type="button"
                className="focus-ring rounded-full px-2 py-0.5 hover:opacity-80"
                style={{ border: "1px dashed var(--color-hairline-strong)", color: "var(--color-text-2)" }}
                onClick={() => setIdea(t(key))}
              >
                {t(`${key}_label`)}
              </button>
            ))}
          </div>
          <fieldset className="flex flex-wrap items-center gap-3 text-[12px]" style={{ color: "var(--color-text-2)" }}>
            <label className="flex items-center gap-1">
              <input type="radio" checked={mode === "auto"} onChange={() => setMode("auto")} />
              {t("auto_mode_auto")}
            </label>
            <label className="flex items-center gap-1">
              <input type="radio" checked={mode === "semi"} onChange={() => setMode("semi")} />
              {t("auto_mode_semi")}
            </label>
            {mode === "semi" && <small style={{ color: "var(--color-text-3)" }}>{t("auto_mode_semi_hint")}</small>}
          </fieldset>
          {(offer.max_target_episodes ?? 1) > 1 && (
            <label className="flex items-center gap-2 text-[12px]" style={{ color: "var(--color-text-2)" }}>
              {t("auto_episodes_label")}
              <select
                className="focus-ring rounded-md px-1.5 py-0.5"
                style={{ border: "1px solid var(--color-hairline-strong)", background: "transparent" }}
                value={episodes}
                onChange={(event) => setEpisodes(Number(event.target.value))}
              >
                {Array.from({ length: offer.max_target_episodes ?? 1 }, (_, index) => (
                  <option key={index + 1} value={index + 1}>
                    {index + 1}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button type="submit" className={BUTTON_CLS} style={PRIMARY_STYLE} disabled={busy || !idea.trim()}>
            {busy ? t("auto_starting") : t("auto_start")}
          </button>
        </form>
      )}
      {runs.length > 1 && (
        <div role="group" aria-label={t("auto_history_filter")} className="flex flex-wrap gap-1 text-[11.5px]">
          {(["all", "active", "done", "failed"] as const).map((filter) => (
            <button
              key={filter}
              type="button"
              aria-pressed={historyFilter === filter}
              className="focus-ring rounded-full px-2 py-0.5"
              style={{
                border: "1px solid var(--color-hairline-strong)",
                background: historyFilter === filter ? "var(--color-accent-dim)" : "transparent",
                color: historyFilter === filter ? "var(--color-accent-2)" : "var(--color-text-3)",
              }}
              onClick={() => setHistoryFilter(filter)}
            >
              {t(`auto_history_${filter}`, { count: runs.filter((item) => inFilter(item.status, filter)).length })}
            </button>
          ))}
        </div>
      )}
      {runs.length > 1 && (
        <label className="flex items-center gap-2 text-[12px]" style={{ color: "var(--color-text-2)" }}>
          {t("auto_history_label")}
          <select
            className="focus-ring rounded-md px-1.5 py-0.5"
            style={{ border: "1px solid var(--color-hairline-strong)", background: "transparent" }}
            value={run?.run_id ?? ""}
            onChange={(event) => setSelected(event.target.value)}
          >
            {shownRuns.map((item) => (
              <option key={item.run_id} value={item.run_id}>
                {t("auto_history_item", {
                  time: new Date(item.created_at).toLocaleString(),
                  status: t(`auto_status_${item.status}`),
                })}
              </option>
            ))}
          </select>
        </label>
      )}
      {run && (
        <div data-run-id={run.run_id} className="space-y-2">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[12px]">
            <span style={{ color: "var(--color-text-2)" }}>
              {t("auto_stage", { stage: t(`auto_stage_${run.stage}`) })}
            </span>
            <span style={{ color: statusTone(run.status) }}>
              {t("auto_status", { status: t(`auto_status_${run.status}`) })}
            </span>
          </div>
          <p className="text-[11.5px]" style={{ color: "var(--color-text-3)" }}>
            {[
              t("auto_detail_started", { time: new Date(run.created_at).toLocaleString() }),
              ...(total === null ? [] : [t("auto_detail_elapsed", { duration: formatDuration(total) })]),
              t("auto_detail_generation", { generation: run.generation }),
              t("auto_detail_evaluations", {
                count: run.final_evaluations ?? 0,
                limit: run.policy.final_evaluation_limit ?? 3,
              }),
              ...(run.repair_counts ?? []).map((repair) =>
                t("auto_detail_repairs", { stage: t(`auto_stage_${repair.stage}`), count: repair.count }),
              ),
            ].join(" · ")}
          </p>
          <ol aria-label={t("auto_steps")} className="m-0 flex list-none flex-wrap gap-1 p-0">
            {STAGES.map((stage, index) => {
              const done = index < reached || run.status === "SUCCEEDED";
              const current = index === reached && run.status !== "SUCCEEDED";
              return (
                <li
                  key={stage}
                  aria-current={current ? "step" : undefined}
                  className="rounded-full px-2 py-0.5 text-[11px]"
                  style={{
                    border: `1px ${done || current ? "solid" : "dashed"} ${
                      current ? statusTone(run.status) : "var(--color-hairline-strong)"
                    }`,
                    color: done ? "var(--color-text-2)" : current ? statusTone(run.status) : "var(--color-text-3)",
                    background: done ? "var(--color-accent-dim)" : "transparent",
                  }}
                >
                  {t(`auto_stage_${stage}`)}
                  {times[stage] && (
                    <span style={{ color: "var(--color-text-3)" }}>
                      {" · "}
                      {formatDuration(times[stage].ms)}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
          {story && (
            <p className="text-[11.5px]" style={{ color: "var(--color-text-3)" }}>
              {t("auto_progress_story", {
                planning: `${story.planning_done}/${story.planning_total}`,
                scenes:
                  story.scenes_planned === null
                    ? String(story.scenes_drafted)
                    : `${story.scenes_drafted}/${story.scenes_planned}`,
                reviews: `${story.reviews_done}/${story.reviews_total}`,
                calls: `${story.generate_calls}/${story.generate_calls_max}`,
              })}
            </p>
          )}
          {active && runProgress && Object.keys(runProgress.tasks).length > 0 && (
            <p className="text-[11.5px]" style={{ color: "var(--color-text-3)" }}>
              {t("auto_progress_tasks", {
                running: runProgress.tasks.running ?? 0,
                queued: runProgress.tasks.queued ?? 0,
                done: runProgress.tasks.succeeded ?? 0,
                failed: runProgress.tasks.failed ?? 0,
              })}
            </p>
          )}
          {active && runProgress?.media && <RunMediaStrip projectName={projectName} media={runProgress.media} />}
          {run.reason && (
            <div
              role={STOPPED.has(run.status) || FAILED.has(run.status) ? "alert" : undefined}
              className="flex flex-wrap items-center gap-2 rounded-md px-2 py-1.5 text-[12px]"
              style={{ border: `1px solid ${statusTone(run.status)}`, color: statusTone(run.status) }}
            >
              <span>{t("auto_reason", { reason: reasonText(run.reason) })}</span>
              <button
                type="button"
                className="focus-ring rounded text-[11.5px] underline underline-offset-2 hover:opacity-80"
                onClick={() => void navigator.clipboard?.writeText(`${run.run_id} ${run.stage} ${run.reason}`)}
              >
                {t("auto_copy_error")}
              </button>
            </div>
          )}
          {run.pending_review && (
            <div
              role="group"
              className="flex flex-wrap items-center gap-2"
              aria-label={t("auto_review_title", { checkpoint: run.pending_review.checkpoint })}
            >
              <p className="text-[12px]" style={{ color: SEVERITY_TONES.warnings.color }}>
                {t("auto_review_title", { checkpoint: t(`auto_checkpoint_${run.pending_review.checkpoint}`) })}
              </p>
              <button
                type="button"
                className={BUTTON_CLS}
                style={PRIMARY_STYLE}
                disabled={busy}
                onClick={() => review("APPROVE")}
              >
                {t("auto_review_approve")}
              </button>
              <button
                type="button"
                className={BUTTON_CLS}
                style={BUTTON_STYLE}
                disabled={busy}
                onClick={() => review("REJECT")}
              >
                {t("auto_review_reject")}
              </button>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {active && !STOPPED.has(run.status) && (
              <button
                type="button"
                className={BUTTON_CLS}
                style={BUTTON_STYLE}
                disabled={busy}
                onClick={() => control("pause")}
              >
                {t("auto_pause")}
              </button>
            )}
            {active && STOPPED.has(run.status) && (
              <button
                type="button"
                className={BUTTON_CLS}
                style={PRIMARY_STYLE}
                disabled={busy}
                onClick={() => control("resume")}
              >
                {t("auto_resume")}
              </button>
            )}
            {active && STOPPED.has(run.status) && (
              <button type="button" className={BUTTON_CLS} style={BUTTON_STYLE} disabled={busy} onClick={switchMode}>
                {run.policy.mode === "auto" ? t("auto_switch_to_semi") : t("auto_switch_to_auto")}
              </button>
            )}
            {active && (
              <button
                type="button"
                className={BUTTON_CLS}
                style={BUTTON_STYLE}
                disabled={busy}
                onClick={() => control("cancel")}
              >
                {t("auto_cancel")}
              </button>
            )}
          </div>
          <RunReportDetails projectName={projectName} runId={run.run_id} version={run.version} />
          {run.status === "SUCCEEDED" && (
            <ul className="m-0 list-none space-y-1 p-0">
              {run.completed_targets.map((output) => {
                const episode = Number(output.target.split(":")[1]);
                const passed = output.quality_decision === "PASS";
                return (
                  <li key={output.target} className="flex flex-wrap items-center gap-2 text-[12px]">
                    <button
                      type="button"
                      className={BUTTON_CLS}
                      style={PRIMARY_STYLE}
                      onClick={() => void download(episode)}
                    >
                      {t("auto_download", { episode })}
                    </button>
                    <span style={{ color: passed ? "var(--color-accent-2)" : SEVERITY_TONES.warnings.color }}>
                      {t(`auto_quality_${output.quality_decision}`)}
                    </span>
                    <span style={{ color: "var(--color-text-3)" }}>
                      {t("auto_size", { size: (output.archive_size / 1_000_000).toFixed(1) })}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
