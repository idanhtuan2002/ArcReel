import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  controlProductionRun,
  downloadProductionOutput,
  listProductionRuns,
  newCommandId,
  reviewProductionRun,
  startProductionRun,
  type ControlAction,
} from "../api/productionRunClient";
import { STOPPED, TERMINAL, type AutomationMode, type RunSnapshot, type StartOffer } from "../api/types";

const POLL_MS = 5000;

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
  const [offer, setOffer] = useState<StartOffer | null>(null);
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [idea, setIdea] = useState("");
  const [mode, setMode] = useState<AutomationMode>("auto");
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
        setRun(list.runs.find((item) => item.project_name === projectName) ?? null);
      } catch (cause) {
        if (signal?.aborted || !mounted.current) return;
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    },
    [projectName],
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

  const act = useCallback(
    async (call: () => Promise<RunSnapshot>) => {
      if (busy) return;
      setBusy(true);
      setError(null);
      try {
        const updated = await call();
        if (mounted.current) setRun(updated);
      } catch (cause) {
        if (mounted.current) setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        if (mounted.current) setBusy(false);
      }
    },
    [busy],
  );

  const start = () => {
    if (!offer?.input_digest || !offer.policy_digests || !idea.trim()) return;
    const command = {
      command_id: newCommandId(),
      mode,
      idea: idea.trim(),
      expected_input_digest: offer.input_digest,
      policy_digest: offer.policy_digests[mode],
    };
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
    const blob = await downloadProductionOutput(projectName, run.run_id, episode);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${projectName}-episode-${episode}.zip`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const active = run !== null && !TERMINAL.has(run.status);
  return (
    <section aria-label={t("auto_title")} data-testid="production-run-panel">
      <h3>{t("auto_title")}</h3>
      {error && <p role="alert">{t("auto_error", { message: error })}</p>}
      {!active && offer && !offer.enabled && <p>{t("auto_unavailable", { reason: offer.reason ?? "" })}</p>}
      {!active && offer?.enabled && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            start();
          }}
        >
          <label>
            {t("auto_idea_label")}
            <textarea
              value={idea}
              placeholder={t("auto_idea_placeholder")}
              onChange={(event) => setIdea(event.target.value)}
            />
          </label>
          <fieldset>
            <label>
              <input type="radio" checked={mode === "auto"} onChange={() => setMode("auto")} />
              {t("auto_mode_auto")}
            </label>
            <label>
              <input type="radio" checked={mode === "semi"} onChange={() => setMode("semi")} />
              {t("auto_mode_semi")}
            </label>
            {mode === "semi" && <small>{t("auto_mode_semi_hint")}</small>}
          </fieldset>
          <button type="submit" disabled={busy || !idea.trim()}>
            {busy ? t("auto_starting") : t("auto_start")}
          </button>
        </form>
      )}
      {run && (
        <div data-run-id={run.run_id}>
          <p>{t("auto_stage", { stage: run.stage })}</p>
          <p>{t("auto_status", { status: run.status })}</p>
          {run.reason && <p>{t("auto_reason", { reason: run.reason })}</p>}
          {run.pending_review && (
            <div role="group" aria-label={t("auto_review_title", { checkpoint: run.pending_review.checkpoint })}>
              <p>
                {t("auto_review_title", { checkpoint: t(`auto_checkpoint_${run.pending_review.checkpoint}`) })}
              </p>
              <button type="button" disabled={busy} onClick={() => review("APPROVE")}>
                {t("auto_review_approve")}
              </button>
              <button type="button" disabled={busy} onClick={() => review("REJECT")}>
                {t("auto_review_reject")}
              </button>
            </div>
          )}
          {active && !STOPPED.has(run.status) && (
            <button type="button" disabled={busy} onClick={() => control("pause")}>
              {t("auto_pause")}
            </button>
          )}
          {active && STOPPED.has(run.status) && (
            <button type="button" disabled={busy} onClick={() => control("resume")}>
              {t("auto_resume")}
            </button>
          )}
          {active && (
            <button type="button" disabled={busy} onClick={() => control("cancel")}>
              {t("auto_cancel")}
            </button>
          )}
          {run.status === "SUCCEEDED" &&
            run.completed_targets.map((output) => {
              const episode = Number(output.target.split(":")[1]);
              return (
                <button key={output.target} type="button" onClick={() => void download(episode)}>
                  {t("auto_download", { episode })}
                </button>
              );
            })}
        </div>
      )}
    </section>
  );
}
