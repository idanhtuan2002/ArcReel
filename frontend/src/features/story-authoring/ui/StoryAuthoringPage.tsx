/**
 * Story authoring of a project (route `story`): turn an idea into a three-chapter short story. The Human
 * greenlights the brief (Gate A), the run writes and reviews on its own, and the Human reads the offered
 * manuscript as a proof with the reviewers' notes beside each scene, ticks every exception, and approves,
 * asks for a revision or discards it. An approved story is exported or handed to the video flow. The server
 * owns every state and verdict; the page only shows them and sends the Human's decisions.
 */
import "./story-authoring.css";

import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { ApiRequestError } from "@/api";

import {
  BLOCKED_PHASES,
  WORKING_PHASES,
  approveRun,
  draftBrief,
  exportRun,
  getRun,
  greenlightAndStart,
  listRoutes,
  listRuns,
  reviseRun,
  runAction,
  sendToVideo,
  type DraftedBrief,
  type Finding,
  type LifecycleAction,
  type OnConflict,
  type Packaging,
  type RunPhase,
  type RunSummary,
  type StoryRoute,
  type StoryRun,
} from "../api/storyClient";

const POLL_MS = 15_000;
const TARGET_MIN = 7000;
const TARGET_MAX = 11000;
const TARGET_DEFAULT = 9000;

/** A refusal in the Human's language: a known server code has its own text, anything else its message. */
function failureText(t: TFunction, failure: unknown, fallback: string): string {
  if (failure instanceof ApiRequestError && failure.code) {
    return t(`story_error_${failure.code}`, { defaultValue: failure.message || fallback });
  }
  return failure instanceof Error && failure.message ? failure.message : fallback;
}

/** Runs one async step with busy and error state that never outlive the component. */
function useStep() {
  const { t } = useTranslation("dashboard");
  const current = useRef<AbortController | null>(null);
  useEffect(() => () => current.current?.abort(), []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const run = useCallback(
    async <T,>(step: (signal: AbortSignal) => Promise<T>, fallback: string): Promise<T | null> => {
      current.current?.abort();
      const controller = new AbortController();
      current.current = controller;
      setBusy(true);
      setError(null);
      setCode(null);
      try {
        const result = await step(controller.signal);
        return controller.signal.aborted ? null : result;
      } catch (failure: unknown) {
        if (!controller.signal.aborted) {
          setError(failureText(t, failure, fallback));
          setCode(failure instanceof ApiRequestError ? (failure.code ?? null) : null);
        }
        return null;
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    },
    [t],
  );
  return { busy, error, code, run };
}

/** Warns before the tab closes while typed text has not been saved. */
function useUnsavedWarning(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
}

function readDraft(key: string): { idea: string; genre: string } {
  try {
    const stored = JSON.parse(sessionStorage.getItem(key) ?? "null") as { idea?: unknown; genre?: unknown } | null;
    return {
      idea: typeof stored?.idea === "string" ? stored.idea : "",
      genre: typeof stored?.genre === "string" ? stored.genre : "",
    };
  } catch {
    return { idea: "", genre: "" };
  }
}

function writeDraft(key: string, draft: { idea: string; genre: string } | null) {
  try {
    if (draft === null || (!draft.idea && !draft.genre)) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(draft));
  } catch {
    // Storage may be unavailable (private mode); the draft then lives only in this page.
  }
}

interface StoryAuthoringPageProps {
  projectName: string;
}

export default function StoryAuthoringPage({ projectName }: StoryAuthoringPageProps) {
  const { t } = useTranslation("dashboard");
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const reload = useCallback(() => setReloadToken((token) => token + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    listRuns(projectName, { signal: controller.signal }).then(
      (found) => {
        if (controller.signal.aborted) return;
        setRuns(found);
        setLoadError(null);
        setSelected((current) => (current && found.some((r) => r.run_id === current) ? current : (found[0]?.run_id ?? null)));
      },
      (failure: unknown) => {
        if (!controller.signal.aborted) setLoadError(failureText(t, failure, t("story_load_failed")));
      },
    );
    return () => controller.abort();
  }, [projectName, reloadToken, t]);

  const showForm = creating || (runs !== null && runs.length === 0);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-bg">
      <header className="sa-header border-b border-hairline py-2.5">
        <p className="font-mono text-[10px] tracking-[0.18em] text-text-3">PROJECT · STORY</p>
        <h1 className="font-editorial text-xl leading-tight text-text">{t("story_title")}</h1>
        <p className="mt-0.5 max-w-2xl text-xs text-text-2">{t("story_subtitle")}</p>
      </header>

      <div className="sa-layout mx-auto w-full max-w-6xl px-4 py-6">
        {loadError ? (
          <div role="alert" className="rounded-md border border-hairline-strong p-4 text-sm text-text-2">
            {loadError}
            <button type="button" onClick={reload} className="sa-btn ml-3">
              {t("story_retry_load")}
            </button>
          </div>
        ) : runs === null ? (
          <p role="status" className="text-sm text-text-3">
            {t("story_loading")}
          </p>
        ) : (
          <>
            <nav aria-labelledby="sa-runs-title" className="sa-runs">
              <div className="flex items-center justify-between gap-2">
                <h2 id="sa-runs-title" className="font-mono text-[11px] tracking-[0.14em] text-text-3">
                  STORIES
                </h2>
                <button type="button" className="sa-btn" onClick={() => setCreating(true)} disabled={showForm}>
                  {t("story_new")}
                </button>
              </div>
              {runs.length === 0 ? (
                <p className="mt-2 text-xs text-text-3">{t("story_runs_empty")}</p>
              ) : (
                <ul className="mt-2 space-y-1">
                  {runs.map((run) => (
                    <li key={run.run_id}>
                      <button
                        type="button"
                        className="sa-run-item"
                        aria-current={!showForm && selected === run.run_id ? "true" : undefined}
                        onClick={() => {
                          setCreating(false);
                          setSelected(run.run_id);
                        }}
                      >
                        <span className="sa-run-idea">{run.idea}</span>
                        <span className="sa-run-meta">
                          {t(`story_phase_${run.phase}`)} · {new Date(run.started_at).toLocaleDateString()}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </nav>
            <main className="min-w-0">
              {showForm ? (
                <NewStory
                  projectName={projectName}
                  onCancel={runs.length > 0 ? () => setCreating(false) : null}
                  onStarted={(runId) => {
                    setCreating(false);
                    setSelected(runId);
                    reload();
                  }}
                />
              ) : selected ? (
                <RunView key={selected} projectName={projectName} runId={selected} onChanged={reload} />
              ) : null}
            </main>
          </>
        )}
      </div>
    </div>
  );
}

// --- brief and Gate A --------------------------------------------------------------------------------

function NewStory({
  projectName,
  onCancel,
  onStarted,
}: {
  projectName: string;
  onCancel: (() => void) | null;
  onStarted: (runId: string) => void;
}) {
  const { t } = useTranslation("dashboard");
  const draftKey = `story-draft:${projectName}`;
  const ids = { idea: useId(), genre: useId(), writer: useId(), judge: useId(), target: useId() };
  const [idea, setIdea] = useState(() => readDraft(draftKey).idea);
  const [genre, setGenre] = useState(() => readDraft(draftKey).genre);
  const [routes, setRoutes] = useState<StoryRoute[] | null>(null);
  const [routesError, setRoutesError] = useState<string | null>(null);
  const [writer, setWriter] = useState("");
  const [judge, setJudge] = useState("");
  const [target, setTarget] = useState(TARGET_DEFAULT);
  const [drafted, setDrafted] = useState<DraftedBrief | null>(null);
  const { busy, error, run } = useStep();

  useUnsavedWarning(Boolean(idea.trim() || genre.trim()));
  useEffect(() => writeDraft(draftKey, { idea, genre }), [draftKey, idea, genre]);

  useEffect(() => {
    const controller = new AbortController();
    listRoutes({ signal: controller.signal }).then(
      (found) => {
        if (controller.signal.aborted) return;
        setRoutes(found);
        setWriter((current) => current || (found[0] ? routeKey(found[0]) : ""));
      },
      (failure: unknown) => {
        if (!controller.signal.aborted) setRoutesError(failureText(t, failure, t("story_routes_failed")));
      },
    );
    return () => controller.abort();
  }, [t]);

  const writerRoute = routes?.find((route) => routeKey(route) === writer) ?? null;
  const judgeRoute = routes?.find((route) => routeKey(route) === judge) ?? null;
  const targetValid = Number.isInteger(target) && target >= TARGET_MIN && target <= TARGET_MAX;
  const ready = Boolean(idea.trim() && genre.trim() && writerRoute && targetValid);

  async function prepare(event: FormEvent) {
    event.preventDefault();
    if (!ready || busy || !writerRoute) return;
    const found = await run(
      (signal) =>
        draftBrief(
          projectName,
          {
            idea: idea.trim(),
            genre: genre.trim(),
            provider_id: writerRoute.provider_id,
            model_id: writerRoute.model_id,
            story_target_syllables: target,
            judge_provider_id: judgeRoute?.provider_id ?? null,
            judge_model_id: judgeRoute?.model_id ?? null,
          },
          { signal },
        ),
      t("story_brief_failed"),
    );
    if (found) setDrafted(found);
  }

  async function greenlight(brief: DraftedBrief) {
    const runId = await run((signal) => greenlightAndStart(projectName, brief, { signal }), t("story_start_failed"));
    if (runId) {
      writeDraft(draftKey, null);
      setIdea("");
      setGenre("");
      onStarted(runId);
    }
  }

  if (drafted) {
    const brief = drafted.brief;
    return (
      <section aria-labelledby="sa-gate-title" className="sa-panel rounded-md border border-hairline p-4">
        <p className="font-mono text-[10px] tracking-[0.14em] text-text-3">GATE A</p>
        <h2 id="sa-gate-title" className="font-editorial text-base text-text">
          {t("story_gate_title")}
        </h2>
        <p className="mt-1 text-xs text-text-2">{t("story_gate_hint")}</p>
        <dl className="sa-brief mt-3">
          <dt>{t("story_field_idea")}</dt>
          <dd>{brief.idea}</dd>
          <dt>{t("story_field_genre")}</dt>
          <dd>{brief.genre}</dd>
          <dt>{t("story_field_writer")}</dt>
          <dd>{brief.selection.model_id}</dd>
          <dt>{t("story_field_judge")}</dt>
          <dd>{brief.judge_selection ? brief.judge_selection.model_id : t("story_judge_same")}</dd>
          <dt>{t("story_field_target")}</dt>
          <dd>{t("story_target_value", { count: brief.story_target_syllables })}</dd>
        </dl>
        <p className="mt-2 font-mono text-[10px] text-text-3" title={drafted.brief_digest}>
          {drafted.brief_digest.slice(0, 19)}…
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className="sa-btn sa-btn-accent" disabled={busy} onClick={() => void greenlight(drafted)}>
            {busy ? t("story_starting") : t("story_greenlight")}
          </button>
          <button type="button" className="sa-btn" disabled={busy} onClick={() => setDrafted(null)}>
            {t("story_edit_brief")}
          </button>
        </div>
        {error ? (
          <p role="alert" className="mt-2 text-sm text-text-2">
            {error}
          </p>
        ) : null}
      </section>
    );
  }

  return (
    <section aria-labelledby="sa-new-title" className="sa-panel rounded-md border border-hairline p-4">
      <h2 id="sa-new-title" className="font-editorial text-base text-text">
        {t("story_new_title")}
      </h2>
      <p className="mt-1 text-xs text-text-2">{t("story_new_hint")}</p>
      <form onSubmit={(event) => void prepare(event)} className="mt-3 space-y-3">
        <fieldset disabled={busy} className="space-y-3">
          <legend className="sr-only">{t("story_new_title")}</legend>
          <div>
            <label htmlFor={ids.idea} className="block text-[11px] text-text-3">
              {t("story_field_idea")}
            </label>
            <textarea
              id={ids.idea}
              required
              rows={5}
              maxLength={4000}
              value={idea}
              placeholder={t("story_idea_placeholder")}
              onChange={(event) => setIdea(event.target.value)}
              className="sa-input"
            />
          </div>
          <div>
            <label htmlFor={ids.genre} className="block text-[11px] text-text-3">
              {t("story_field_genre")}
            </label>
            <input
              id={ids.genre}
              required
              maxLength={200}
              value={genre}
              placeholder={t("story_genre_placeholder")}
              onChange={(event) => setGenre(event.target.value)}
              className="sa-input"
            />
          </div>
          {routesError ? (
            <p role="alert" className="text-sm text-text-2">
              {routesError}
            </p>
          ) : routes === null ? (
            <p role="status" className="text-xs text-text-3">
              {t("story_routes_loading")}
            </p>
          ) : routes.length === 0 ? (
            <p className="rounded-md border border-dashed border-hairline-strong p-3 text-xs text-text-2">
              {t("story_routes_empty")}
            </p>
          ) : (
            <div className="sa-grid">
              <div>
                <label htmlFor={ids.writer} className="block text-[11px] text-text-3">
                  {t("story_field_writer")}
                </label>
                <select id={ids.writer} value={writer} onChange={(event) => setWriter(event.target.value)} className="sa-input">
                  {routes.map((route) => (
                    <option key={routeKey(route)} value={routeKey(route)}>
                      {route.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor={ids.judge} className="block text-[11px] text-text-3">
                  {t("story_field_judge")}
                </label>
                <select id={ids.judge} value={judge} onChange={(event) => setJudge(event.target.value)} className="sa-input">
                  <option value="">{t("story_judge_same")}</option>
                  {routes
                    .filter((route) => routeKey(route) !== writer)
                    .map((route) => (
                      <option key={routeKey(route)} value={routeKey(route)}>
                        {route.label}
                      </option>
                    ))}
                </select>
              </div>
            </div>
          )}
          <div>
            <label htmlFor={ids.target} className="block text-[11px] text-text-3">
              {t("story_field_target")}
            </label>
            <input
              id={ids.target}
              type="number"
              min={TARGET_MIN}
              max={TARGET_MAX}
              step={500}
              value={target}
              onChange={(event) => setTarget(Number(event.target.value))}
              aria-describedby={`${ids.target}-hint`}
              className="sa-input sa-input-short"
            />
            <p id={`${ids.target}-hint`} className="mt-0.5 text-[11px] text-text-3">
              {t("story_target_hint", { min: TARGET_MIN, max: TARGET_MAX })}
            </p>
          </div>
        </fieldset>
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={busy || !ready} className="sa-btn sa-btn-accent">
            {busy ? t("story_preparing") : t("story_prepare")}
          </button>
          {onCancel ? (
            <button type="button" className="sa-btn" disabled={busy} onClick={onCancel}>
              {t("story_cancel")}
            </button>
          ) : null}
        </div>
        {error ? (
          <p role="alert" className="text-sm text-text-2">
            {error}
          </p>
        ) : null}
      </form>
    </section>
  );
}

function routeKey(route: StoryRoute): string {
  return `${route.provider_id}/${route.model_id}`;
}

// --- one run -------------------------------------------------------------------------------------------

const STAGES = ["brief", "writing", "review", "approved", "video"] as const;
type Stage = (typeof STAGES)[number];

function stageOf(run: StoryRun): Stage {
  if (run.handoff?.done) return "video";
  if (run.phase === "COMMITTED" || run.phase === "WITHDRAWN") return "approved";
  if (run.phase === "READY_FOR_APPROVAL" || run.phase === "APPROVING" || run.phase === "PARTIALLY_COMMITTED" || run.phase === "COMMIT_BLOCKED")
    return "review";
  if (run.phase === "AWAITING_GATE_A") return "brief";
  return "writing";
}

function RunView({ projectName, runId, onChanged }: { projectName: string; runId: string; onChanged: () => void }) {
  const { t } = useTranslation("dashboard");
  const [run, setRun] = useState<StoryRun | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const reload = useCallback(() => setReloadToken((token) => token + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const load = () => {
      getRun(projectName, runId, { signal: controller.signal }).then(
        (found) => {
          if (controller.signal.aborted) return;
          setRun(found);
          setLoadError(null);
          if (WORKING_PHASES.has(found.phase)) timer = window.setTimeout(load, POLL_MS);
        },
        (failure: unknown) => {
          if (!controller.signal.aborted) setLoadError(failureText(t, failure, t("story_load_failed")));
        },
      );
    };
    load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [projectName, runId, reloadToken, t]);

  const changed = useCallback(
    (next: StoryRun | null) => {
      if (next) setRun(next);
      else reload();
      onChanged();
    },
    [onChanged, reload],
  );

  if (loadError) {
    return (
      <div role="alert" className="rounded-md border border-hairline-strong p-4 text-sm text-text-2">
        {loadError}
        <button type="button" onClick={reload} className="sa-btn ml-3">
          {t("story_retry_load")}
        </button>
      </div>
    );
  }
  if (!run) {
    return (
      <p role="status" className="text-sm text-text-3">
        {t("story_loading")}
      </p>
    );
  }

  const stage = stageOf(run);
  return (
    <article aria-labelledby="sa-run-title" className="space-y-4">
      <header className="sa-panel rounded-md border border-hairline p-4">
        <p className="font-mono text-[10px] tracking-[0.12em] text-text-3">{run.brief.genre.toUpperCase()}</p>
        <h2 id="sa-run-title" className="font-editorial text-base text-text">
          {run.brief.idea}
        </h2>
        <ol className="sa-stages mt-3" aria-label={t("story_stages_label")}>
          {STAGES.map((item, index) => {
            const reached = STAGES.indexOf(stage) >= index;
            return (
              <li key={item} aria-current={item === stage ? "step" : undefined} data-reached={reached || undefined}>
                {t(`story_stage_${item}`)}
              </li>
            );
          })}
        </ol>
        <p className="mt-2 text-xs text-text-2" role="status">
          {t(`story_phase_${run.phase}`)} — {t(`story_phase_hint_${run.phase}`)}
        </p>
        <UsageLine run={run} />
      </header>
      <PhasePanel projectName={projectName} run={run} onChanged={changed} />
    </article>
  );
}

function UsageLine({ run }: { run: StoryRun }) {
  const { t } = useTranslation("dashboard");
  const minutes = Math.round(run.usage.model_milliseconds / 60000);
  return (
    <p className="mt-1 font-mono text-[10px] text-text-3">
      {t("story_usage", {
        calls: run.usage.generate_calls,
        input: Math.round(run.usage.input_tokens / 1000),
        output: Math.round(run.usage.output_tokens / 1000),
        minutes,
      })}
    </p>
  );
}

function PhasePanel({ projectName, run, onChanged }: { projectName: string; run: StoryRun; onChanged: (run: StoryRun | null) => void }) {
  const phase: RunPhase = run.phase;
  if (phase === "READY_FOR_APPROVAL" && run.offered) {
    return <Review projectName={projectName} run={run} onChanged={onChanged} />;
  }
  if (phase === "COMMITTED") {
    return <Approved projectName={projectName} run={run} onChanged={onChanged} />;
  }
  if (BLOCKED_PHASES.has(phase)) {
    return (
      <Lifecycle projectName={projectName} run={run} actions={["retry", "discard"]} onChanged={onChanged}>
        <Blocked run={run} />
      </Lifecycle>
    );
  }
  const actions: Record<RunPhase, LifecycleAction[]> = {
    RUNNING: ["discard"],
    AWAITING_GATE_A: ["discard"],
    APPROVING: ["resume", "abort"],
    PARTIALLY_COMMITTED: ["resume", "abort"],
    COMMIT_BLOCKED: ["resume", "abort"],
    RECOVERY_INCONSISTENT: ["discard"],
    READY_FOR_APPROVAL: ["discard"],
    COMMITTED: [],
    WITHDRAWN: [],
    DISCARDED: [],
    ABORTED_PARTIAL: [],
    BLOCKED_BUDGET: [],
    BLOCKED_QUALITY: [],
    BLOCKED_BINDING_MISMATCH: [],
    BLOCKED_PROPAGATION: [],
    MODEL_UNAVAILABLE: [],
  };
  return (
    <Lifecycle projectName={projectName} run={run} actions={actions[phase]} onChanged={onChanged}>
      {phase === "ABORTED_PARTIAL" || phase === "PARTIALLY_COMMITTED" || phase === "COMMIT_BLOCKED" ? (
        <CommittedSteps run={run} />
      ) : null}
    </Lifecycle>
  );
}

function Blocked({ run }: { run: StoryRun }) {
  const { t } = useTranslation("dashboard");
  return (
    <div>
      {run.block_reason ? <p className="text-sm text-text">{run.block_reason}</p> : null}
      {run.blocked_findings.length > 0 ? (
        <ul className="mt-2 space-y-2" aria-label={t("story_blocked_findings")}>
          {run.blocked_findings.map((finding, index) => (
            <li key={`${finding.node_id}-${index}`} className="sa-note" data-severity={finding.severity}>
              <FindingBody finding={finding} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function CommittedSteps({ run }: { run: StoryRun }) {
  const { t } = useTranslation("dashboard");
  const steps = run.offered?.completed_steps ?? [];
  return (
    <p className="text-xs text-text-2">
      {steps.length === 0 ? t("story_committed_none") : t("story_committed_steps", { steps: steps.join(", ") })}
    </p>
  );
}

/** A run's lifecycle actions; each is a Human decision, and Discard and Abort ask once more. */
function Lifecycle({
  projectName,
  run,
  actions,
  onChanged,
  children,
}: {
  projectName: string;
  run: StoryRun;
  actions: LifecycleAction[];
  onChanged: (run: StoryRun | null) => void;
  children?: ReactNode;
}) {
  const { t } = useTranslation("dashboard");
  const { busy, error, run: step } = useStep();
  const [confirming, setConfirming] = useState<LifecycleAction | null>(null);

  async function act(action: LifecycleAction) {
    if ((action === "discard" || action === "abort" || action === "withdraw") && confirming !== action) {
      setConfirming(action);
      return;
    }
    setConfirming(null);
    const next = await step((signal) => runAction(projectName, run.run_id, action, { signal }), t("story_action_failed"));
    if (next) onChanged(next);
  }

  if (!children && actions.length === 0) return null;
  return (
    <section className="sa-panel rounded-md border border-hairline p-4" aria-label={t("story_actions_label")}>
      {children}
      {actions.length > 0 ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {actions.map((action) => (
            <button
              key={action}
              type="button"
              disabled={busy}
              className={action === "retry" || action === "resume" ? "sa-btn sa-btn-accent" : "sa-btn"}
              onClick={() => void act(action)}
            >
              {confirming === action ? t(`story_confirm_${action}`) : t(`story_action_${action}`)}
            </button>
          ))}
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="mt-2 text-sm text-text-2">
          {error}
        </p>
      ) : null}
    </section>
  );
}

// --- touchpoint 2 ----------------------------------------------------------------------------------

function FindingBody({ finding }: { finding: Finding }) {
  const { t } = useTranslation("dashboard");
  return (
    <>
      <span className="sa-note-kind">{t(`story_severity_${finding.severity}`)}</span>
      <span className="sa-note-text">{finding.message}</span>
      {finding.quote ? <q className="sa-note-quote">{finding.quote}</q> : null}
    </>
  );
}

/** Touchpoint 2: the manuscript as a proof with notes beside each scene, the packaging, and the decision. */
function Review({ projectName, run, onChanged }: { projectName: string; run: StoryRun; onChanged: (run: StoryRun | null) => void }) {
  const { t } = useTranslation("dashboard");
  const offered = run.offered!;
  const byScene = useMemo(() => {
    const notes = new Map<string, Finding[]>();
    for (const finding of offered.findings) {
      const list = notes.get(finding.node_id) ?? [];
      list.push(finding);
      notes.set(finding.node_id, list);
    }
    return notes;
  }, [offered.findings]);
  const exceptions = offered.findings.filter((finding) => finding.id && offered.exceptions_offered.includes(finding.id));
  const sceneIds = new Set(offered.scenes.map((scene) => scene.node_id));
  const general = offered.findings.filter((finding) => !sceneIds.has(finding.node_id));
  const chapters = [...new Set(offered.scenes.map((scene) => scene.chapter))];

  return (
    <>
      <section aria-labelledby="sa-proof-title" className="sa-proof rounded-md border border-hairline">
        <h3 id="sa-proof-title" className="sa-proof-head font-mono text-[11px] tracking-[0.14em] text-text-3">
          {t("story_proof_title")}
        </h3>
        {offered.packaging ? <PackagingSheet packaging={offered.packaging} /> : null}
        {chapters.map((chapter) => (
          <section key={chapter} aria-label={t("story_chapter", { number: chapter })}>
            <h4 className="sa-chapter font-editorial text-text">{t("story_chapter", { number: chapter })}</h4>
            {offered.scenes
              .filter((scene) => scene.chapter === chapter)
              .map((scene) => {
                const notes = byScene.get(scene.node_id) ?? [];
                return (
                  <div key={scene.node_id} className="sa-scene">
                    <div className="sa-scene-text">
                      <p className="sa-scene-mark font-mono text-[10px] text-text-3">
                        {chapter}.{scene.scene}
                      </p>
                      {scene.text.split(/\n\s*\n/).map((paragraph, index) => (
                        <p key={index}>{paragraph}</p>
                      ))}
                    </div>
                    <aside className="sa-margin" aria-label={t("story_notes_for", { scene: `${chapter}.${scene.scene}` })}>
                      {notes.map((finding, index) => (
                        <p key={finding.id ?? index} className="sa-note" data-severity={finding.severity}>
                          <FindingBody finding={finding} />
                        </p>
                      ))}
                    </aside>
                  </div>
                );
              })}
          </section>
        ))}
        {general.length > 0 ? (
          <section className="sa-general" aria-label={t("story_general_notes")}>
            <h4 className="font-mono text-[11px] tracking-[0.14em] text-text-3">{t("story_general_notes")}</h4>
            {general.map((finding, index) => (
              <p key={finding.id ?? index} className="sa-note" data-severity={finding.severity}>
                <FindingBody finding={finding} />
              </p>
            ))}
          </section>
        ) : null}
      </section>
      <Decision projectName={projectName} run={run} exceptions={exceptions} onChanged={onChanged} />
    </>
  );
}

function PackagingSheet({ packaging }: { packaging: Packaging }) {
  const { t } = useTranslation("dashboard");
  return (
    <section className="sa-packaging" aria-label={t("story_packaging")}>
      <p className="sa-title font-editorial text-text">{packaging.titles[0]?.title}</p>
      <p className="mt-1 text-xs text-text-3">
        {t("story_other_titles")}: {packaging.titles.slice(1).map((title) => title.title).join(" · ")}
      </p>
      {packaging.blurbs.map((blurb, index) => (
        <blockquote key={index} className="sa-blurb">
          {blurb}
        </blockquote>
      ))}
      <ul className="sa-points">
        {packaging.selling_points.map((point) => (
          <li key={point.point}>{point.point}</li>
        ))}
      </ul>
      <p className="font-mono text-[10px] text-text-3">{packaging.tags.join(" · ")}</p>
    </section>
  );
}

function Decision({
  projectName,
  run,
  exceptions,
  onChanged,
}: {
  projectName: string;
  run: StoryRun;
  exceptions: Finding[];
  onChanged: (run: StoryRun | null) => void;
}) {
  const { t } = useTranslation("dashboard");
  const offered = run.offered!;
  const ids = { target: useId(), note: useId() };
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [target, setTarget] = useState("chapter[1]");
  const [note, setNote] = useState("");
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const { busy, error, code, run: step } = useStep();

  useUnsavedWarning(Boolean(note.trim()));
  const allTicked = exceptions.every((finding) => finding.id && ticked.has(finding.id));
  const chapters = [...new Set(offered.scenes.map((scene) => scene.chapter))];

  async function approve() {
    if (!allTicked || busy) return;
    const next = await step(
      (signal) => approveRun(projectName, run.run_id, offered.manifest_digest, [...ticked], { signal }),
      t("story_approve_failed"),
    );
    if (next) onChanged(next);
  }

  async function revise(event: FormEvent) {
    event.preventDefault();
    if (!note.trim() || busy) return;
    const next = await step((signal) => reviseRun(projectName, run.run_id, target, note.trim(), { signal }), t("story_revise_failed"));
    if (next) {
      setNote("");
      onChanged(next);
    }
  }

  async function discard() {
    if (!confirmDiscard) {
      setConfirmDiscard(true);
      return;
    }
    const next = await step((signal) => runAction(projectName, run.run_id, "discard", { signal }), t("story_action_failed"));
    if (next) onChanged(next);
  }

  return (
    <section aria-labelledby="sa-decision-title" className="sa-panel rounded-md border border-hairline p-4">
      <p className="font-mono text-[10px] tracking-[0.14em] text-text-3">TOUCHPOINT 2</p>
      <h3 id="sa-decision-title" className="font-editorial text-base text-text">
        {t("story_decision_title")}
      </h3>
      {exceptions.length > 0 ? (
        <fieldset className="mt-3 space-y-2" disabled={busy}>
          <legend className="text-xs text-text-2">{t("story_exceptions_legend", { count: exceptions.length })}</legend>
          {exceptions.map((finding) => (
            <label key={finding.id} className="sa-exception">
              <input
                type="checkbox"
                checked={ticked.has(finding.id!)}
                onChange={(event) => {
                  const next = new Set(ticked);
                  if (event.target.checked) next.add(finding.id!);
                  else next.delete(finding.id!);
                  setTicked(next);
                }}
              />
              <span>
                <FindingBody finding={finding} />
              </span>
            </label>
          ))}
        </fieldset>
      ) : (
        <p className="mt-2 text-xs text-text-2">{t("story_no_exceptions")}</p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" className="sa-btn sa-btn-accent" disabled={busy || !allTicked} onClick={() => void approve()}>
          {t("story_approve")}
        </button>
        <button type="button" className="sa-btn" disabled={busy} onClick={() => void discard()}>
          {confirmDiscard ? t("story_confirm_discard") : t("story_action_discard")}
        </button>
        {!allTicked ? <span className="text-[11px] text-text-3">{t("story_approve_needs_ticks")}</span> : null}
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-text-2">
          {error}
          {code === "STALE_MANIFEST" ? (
            <button type="button" className="sa-btn ml-3" onClick={() => onChanged(null)}>
              {t("story_reload_manuscript")}
            </button>
          ) : null}
        </p>
      ) : null}

      <form onSubmit={(event) => void revise(event)} className="sa-revise mt-4 space-y-2">
        <h4 className="text-xs text-text">{t("story_revise_title")}</h4>
        <fieldset disabled={busy} className="sa-grid">
          <legend className="sr-only">{t("story_revise_title")}</legend>
          <div>
            <label htmlFor={ids.target} className="block text-[11px] text-text-3">
              {t("story_revise_target")}
            </label>
            <select id={ids.target} value={target} onChange={(event) => setTarget(event.target.value)} className="sa-input">
              {chapters.map((chapter) => (
                <option key={chapter} value={`chapter[${chapter}]`}>
                  {t("story_chapter", { number: chapter })}
                </option>
              ))}
              {offered.scenes.map((scene) => (
                <option key={scene.node_id} value={scene.node_id}>
                  {t("story_scene", { chapter: scene.chapter, scene: scene.scene })}
                </option>
              ))}
              <option value="outline">{t("story_target_outline")}</option>
              <option value="packaging">{t("story_target_packaging")}</option>
            </select>
          </div>
          <div className="sa-grid-wide">
            <label htmlFor={ids.note} className="block text-[11px] text-text-3">
              {t("story_revise_note")}
            </label>
            <textarea
              id={ids.note}
              rows={3}
              maxLength={2000}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              className="sa-input"
            />
          </div>
        </fieldset>
        <button type="submit" className="sa-btn" disabled={busy || !note.trim()}>
          {t("story_revise")}
        </button>
      </form>
    </section>
  );
}

// --- after approval ----------------------------------------------------------------------------------

function Approved({ projectName, run, onChanged }: { projectName: string; run: StoryRun; onChanged: (run: StoryRun | null) => void }) {
  const { t } = useTranslation("dashboard");
  const { busy, error, code, run: step } = useStep();
  const [confirmWithdraw, setConfirmWithdraw] = useState(false);
  const handedOff = run.handoff?.done ? run.handoff : null;
  const title = run.offered?.packaging?.titles[0]?.title ?? "story";

  async function download() {
    const blob = await step((signal) => exportRun(projectName, run.run_id, { signal }), t("story_export_failed"));
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${title}.md`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function handOff(onConflict: OnConflict) {
    // The server binds a hand-off to its first command; a pending one is finished with the same command.
    const commandId = run.handoff?.command_id ?? crypto.randomUUID();
    const sent = await step((signal) => sendToVideo(projectName, run.run_id, commandId, onConflict, { signal }), t("story_handoff_failed"));
    onChanged(null);
    return sent;
  }

  async function withdraw() {
    if (!confirmWithdraw) {
      setConfirmWithdraw(true);
      return;
    }
    const next = await step((signal) => runAction(projectName, run.run_id, "withdraw", { signal }), t("story_action_failed"));
    if (next) onChanged(next);
  }

  return (
    <section aria-labelledby="sa-approved-title" className="sa-panel rounded-md border border-hairline p-4">
      <h3 id="sa-approved-title" className="font-editorial text-base text-text">
        {title}
      </h3>
      {handedOff ? (
        <p className="mt-1 text-xs text-text-2">{t("story_handed_off", { path: handedOff.path })}</p>
      ) : (
        <p className="mt-1 text-xs text-text-2">{t("story_approved_hint")}</p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className="sa-btn" disabled={busy} onClick={() => void download()}>
          {t("story_export")}
        </button>
        {handedOff ? null : (
          <button type="button" className="sa-btn sa-btn-accent" disabled={busy} onClick={() => void handOff("fail")}>
            {t("story_send_to_video")}
          </button>
        )}
        <button type="button" className="sa-btn" disabled={busy} onClick={() => void withdraw()}>
          {confirmWithdraw ? t("story_confirm_withdraw") : t("story_action_withdraw")}
        </button>
      </div>
      {confirmWithdraw && handedOff ? <p className="mt-2 text-[11px] text-text-3">{t("story_withdraw_video_note")}</p> : null}
      {error ? (
        <div role="alert" className="mt-2 text-sm text-text-2">
          {error}
          {code === "UPLOAD_FAILED" ? (
            <span className="ml-3 inline-flex gap-2">
              <button type="button" className="sa-btn" disabled={busy} onClick={() => void handOff("rename")}>
                {t("story_handoff_rename")}
              </button>
              <button type="button" className="sa-btn" disabled={busy} onClick={() => void handOff("replace")}>
                {t("story_handoff_replace")}
              </button>
            </span>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
