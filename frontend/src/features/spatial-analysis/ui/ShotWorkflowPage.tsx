/**
 * The Take shot workflow of one episode (route `episodes/:episodeId/shots`): each registered Shot target
 * goes from two bound frames through a human pair review, spatial analysis and promotion to a generated
 * shot that Gate C approves as its master. Only the next step of the selected target is enabled.
 */
import "./spatial.css";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "wouter";
import { ArrowLeft } from "lucide-react";

import { enqueueR2Shot } from "@/actions/generation";
import { WORKSPACE_ROUTE_EPISODES } from "@/app-routes";
import { isResourceBusy } from "@/stores/tasks-store";

import {
  deriveSpatialFrame,
  executeSpatial,
  getSpatialRevision,
  listSpatialSources,
  type CandidateHead,
  type SpatialAssertion,
  type SpatialSource,
} from "../api/spatialClient";
import {
  acknowledgeFrame,
  approveShot,
  createBinding,
  decidePair,
  fetchReviewFrame,
  getCandidateHead,
  listShotTargets,
  openReview,
  previewPromotion,
  promote,
  sha256Digest,
  SHOT_PROFILE_REF,
  workflowCandidateId,
  type PairObservations,
  type ReviewRole,
  type ReviewSnapshot,
  type ShotTargetState,
} from "../api/shotWorkflowClient";

export const STEPS = ["bind", "review", "analyze", "promote", "generate", "approve"] as const;
export type Step = (typeof STEPS)[number] | "done";

const FINISHED_SHOT = "succeeded";
const RETRYABLE_SHOT = new Set(["failed", "cancelled"]);

/** The one step a target can take next, from server state alone. */
export function nextStep(target: ShotTargetState, head: CandidateHead | null): Step {
  if (target.master_version !== null) return "done";
  if (target.binding.has_spatial_set) {
    if (target.shot === null || RETRYABLE_SHOT.has(target.shot.status)) return "generate";
    return target.shot.status === FINISHED_SHOT ? "approve" : "generate";
  }
  if (target.binding.status !== "current") return "bind";
  if (target.pair.status !== "approved" || target.pair.binding_version !== target.binding.binding_version) {
    return "review";
  }
  return head === null ? "analyze" : "promote";
}

function errorMessage(error: unknown): string | null {
  return error instanceof Error && error.message ? error.message : null;
}

interface ShotWorkflowPageProps {
  projectName: string;
  episode: number;
}

export default function ShotWorkflowPage({ projectName, episode }: ShotWorkflowPageProps) {
  const { t } = useTranslation("dashboard");
  const [targets, setTargets] = useState<ShotTargetState[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [found, setFound] = useState<{ candidateId: string; head: CandidateHead | null } | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const reload = useCallback(() => setReloadToken((token) => token + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    listShotTargets(projectName, { signal: controller.signal }).then(
      (listed) => {
        if (controller.signal.aborted) return;
        setTargets(listed);
        setListError(null);
        setSelectedId((id) => id ?? listed[0]?.target_ref.target_id ?? null);
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setListError(errorMessage(error) ?? t("shot_workflow_load_failed"));
      },
    );
    return () => controller.abort();
  }, [projectName, reloadToken, t]);

  const selected = targets?.find((target) => target.target_ref.target_id === selectedId) ?? null;
  const pairVersion = selected?.pair.status === "approved" ? selected.pair.binding_version : null;
  const candidateId =
    selected && pairVersion !== null ? workflowCandidateId(selected.target_ref.target_id, pairVersion) : null;
  // A head read for another candidate (or before a reload) never stands in for this one.
  const head = found !== null && found.candidateId === candidateId ? found.head : null;

  useEffect(() => {
    if (candidateId === null) return;
    const controller = new AbortController();
    getCandidateHead(projectName, candidateId, { signal: controller.signal }).then(
      (current) => {
        if (!controller.signal.aborted) setFound({ candidateId, head: current });
      },
      () => undefined,
    );
    return () => controller.abort();
  }, [projectName, candidateId, reloadToken]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-bg">
      <header className="sp-header flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-hairline py-2.5">
        <Link
          href={`/${WORKSPACE_ROUTE_EPISODES}/${episode}`}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-text-3 hover:text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        >
          <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
          {t("spatial_back")}
        </Link>
        <div className="min-w-0">
          <p className="font-mono text-[10px] tracking-[0.18em] text-text-3">
            EPISODE {String(episode).padStart(2, "0")} · SHOTS
          </p>
          <h1 className="truncate font-editorial text-xl leading-tight text-text">{t("shot_workflow_title")}</h1>
        </div>
      </header>

      <main className="sw-layout mx-auto w-full max-w-6xl px-4 py-6">
        {listError ? (
          <div role="alert" className="rounded-md border border-hairline-strong p-4 text-sm text-text-2">
            {listError}
            <button type="button" onClick={reload} className="sw-btn ml-3">
              {t("spatial_retry")}
            </button>
          </div>
        ) : targets === null ? (
          <p role="status" className="text-sm text-text-3">
            {t("shot_workflow_loading")}
          </p>
        ) : targets.length === 0 ? (
          <p className="rounded-md border border-dashed border-hairline-strong p-4 text-sm text-text-2">
            {t("shot_workflow_empty")}
          </p>
        ) : (
          <>
            <nav aria-label={t("shot_workflow_targets")} className="sw-list">
              <ul className="space-y-2">
                {targets.map((target) => {
                  const id = target.target_ref.target_id;
                  const step = nextStep(target, id === selectedId ? head : null);
                  return (
                    <li key={id}>
                      <button
                        type="button"
                        aria-current={id === selectedId ? "true" : undefined}
                        onClick={() => setSelectedId(id)}
                        className="sw-target w-full rounded-md p-3 text-left"
                      >
                        <span className="block font-mono text-[11px] tracking-[0.08em] text-text">{id}</span>
                        <span className="mt-0.5 block truncate text-xs text-text-2">{target.purpose}</span>
                        <Slate step={step} />
                      </button>
                    </li>
                  );
                })}
              </ul>
            </nav>
            {selected ? (
              <TargetPanel
                key={selected.target_ref.target_id}
                projectName={projectName}
                episode={episode}
                target={selected}
                head={head}
                onChanged={reload}
              />
            ) : null}
          </>
        )}
      </main>
    </div>
  );
}

/** Six marks, one per step: done marks are filled, the next one is outlined in the accent. */
function Slate({ step }: { step: Step }) {
  const { t } = useTranslation("dashboard");
  const reached = step === "done" ? STEPS.length : STEPS.indexOf(step);
  return (
    <span
      className="sw-slate mt-2 flex gap-1"
      role="img"
      aria-label={step === "done" ? t("shot_workflow_step_done") : t(`shot_workflow_step_${step}`)}
    >
      {STEPS.map((name, index) => (
        <span
          key={name}
          className={index < reached ? "sw-mark sw-mark-done" : index === reached ? "sw-mark sw-mark-next" : "sw-mark"}
        />
      ))}
    </span>
  );
}

interface PanelProps {
  projectName: string;
  episode: number;
  target: ShotTargetState;
  head: CandidateHead | null;
  onChanged: () => void;
}

function TargetPanel(props: PanelProps) {
  const { t } = useTranslation("dashboard");
  const step = nextStep(props.target, props.head);
  return (
    <section aria-labelledby="sw-step" className="sw-panel rounded-md border border-hairline-strong bg-surface-2 p-4">
      <p className="font-mono text-[10px] tracking-[0.18em] text-text-3">
        {step === "done" ? "DONE" : `STEP ${STEPS.indexOf(step) + 1} / ${STEPS.length}`}
      </p>
      <h2 id="sw-step" className="mt-1 font-editorial text-lg text-text">
        {step === "done" ? t("shot_workflow_step_done") : t(`shot_workflow_step_${step}`)}
      </h2>
      <p className="mt-1 max-w-2xl text-xs text-text-3">{t(`shot_workflow_hint_${step}`)}</p>
      <div className="mt-4">
        {step === "bind" ? <BindStep {...props} /> : null}
        {step === "review" ? <ReviewStep {...props} /> : null}
        {step === "analyze" ? <AnalyzeStep {...props} /> : null}
        {step === "promote" ? <PromoteStep {...props} /> : null}
        {step === "generate" ? <GenerateStep {...props} /> : null}
        {step === "approve" ? <ApproveStep {...props} /> : null}
        {step === "done" ? (
          <p className="text-sm text-text-2">{t("shot_workflow_master", { version: props.target.master_version })}</p>
        ) : null}
      </div>
    </section>
  );
}

/** Runs one write at a time, shows the server's refusal, and reloads the target list on success. */
function useStepAction(onChanged: () => void) {
  const { t } = useTranslation("dashboard");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const run = useCallback(
    async (operation: (signal: AbortSignal) => Promise<void>, reload = true) => {
      controller.current?.abort();
      const current = new AbortController();
      controller.current = current;
      setBusy(true);
      setError(null);
      try {
        await operation(current.signal);
        if (!current.signal.aborted && reload) onChanged();
      } catch (caught) {
        if (!current.signal.aborted) setError(errorMessage(caught) ?? t("shot_workflow_action_failed"));
      } finally {
        if (!current.signal.aborted) setBusy(false);
      }
    },
    [onChanged, t],
  );
  return { busy, error, run };
}

function StepError({ error }: { error: string | null }) {
  return error ? (
    <p role="alert" className="mt-3 text-sm text-danger">
      {error}
    </p>
  ) : null;
}

function BindStep({ projectName, episode, target, onChanged }: PanelProps) {
  const { t } = useTranslation("dashboard");
  const { busy, error, run } = useStepAction(onChanged);
  const [sources, setSources] = useState<SpatialSource[] | null>(null);
  const [keys, setKeys] = useState<[string, string]>(["", ""]);
  const [frameIndex, setFrameIndex] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listSpatialSources(projectName, episode, { signal: controller.signal }).then(
      (listed) => {
        if (controller.signal.aborted) return;
        setSources(listed);
        setKeys([listed[0]?.artifact_key ?? "", listed[1]?.artifact_key ?? ""]);
      },
      () => {
        if (!controller.signal.aborted) setSources([]);
      },
    );
    return () => controller.abort();
  }, [projectName, episode]);

  if (sources === null) return <p className="text-xs text-text-3">{t("spatial_sources_loading")}</p>;
  if (sources.length < 2) return <p className="text-sm text-text-2">{t("spatial_sources_empty")}</p>;
  const chosen = keys.map((key) => sources.find((source) => source.artifact_key === key));
  const same = keys[0] === keys[1];

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        const [first, second] = chosen;
        if (!first || !second || same) return;
        void run(async (signal) => {
          const frames = await Promise.all(
            [first, second].map((source) => deriveSpatialFrame(projectName, source, frameIndex, { signal })),
          );
          await createBinding(
            projectName,
            target.target_ref,
            [frames[0], frames[1]].map(({ receipt_id, receipt_digest }) => ({ receipt_id, receipt_digest })) as [
              { receipt_id: string; receipt_digest: string },
              { receipt_id: string; receipt_digest: string },
            ],
            { signal },
          );
        });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {[0, 1].map((slot) => (
          <label key={slot} className="block text-xs text-text-2">
            {t("shot_workflow_bind_view", { index: slot + 1 })}
            <select
              value={keys[slot]}
              disabled={busy}
              onChange={(event) =>
                setKeys((current) =>
                  slot === 0 ? [event.target.value, current[1]] : [current[0], event.target.value],
                )
              }
              className="sw-input mt-1"
            >
              {sources.map((source) => (
                <option key={source.artifact_key} value={source.artifact_key}>
                  {source.shot_id} · v{source.master_version}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <label className="mt-3 block max-w-[10rem] text-xs text-text-2">
        {t("spatial_frame_label")}
        <input
          type="number"
          min={0}
          step={1}
          value={frameIndex}
          disabled={busy}
          onChange={(event) => setFrameIndex(Math.max(0, Math.floor(Number(event.target.value) || 0)))}
          className="sw-input mt-1 font-mono"
        />
      </label>
      {same ? <p className="mt-2 text-xs text-warn">{t("spatial_same_shot")}</p> : null}
      <button type="submit" disabled={busy || same} className="sp-btn-accent sw-primary mt-4">
        {t("shot_workflow_bind_action")}
      </button>
      <StepError error={error} />
    </form>
  );
}

interface ReviewedFrame {
  sessionId: string;
  role: ReviewRole;
  url: string;
  verified: boolean;
  attemptId: string;
  pngDigest: string;
  acknowledged: boolean;
}

const EMPTY_OBSERVATIONS = { view_coverage: "", camera_center: "", yaw_relation: "", rejection_reason: "" };

function ReviewStep({ projectName, target, onChanged }: PanelProps) {
  const { t } = useTranslation("dashboard");
  const { busy, error, run } = useStepAction(onChanged);
  const [snapshot, setSnapshot] = useState<ReviewSnapshot | null>(null);
  const [frames, setFrames] = useState<ReviewedFrame[]>([]);
  const [notes, setNotes] = useState(EMPTY_OBSERVATIONS);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const urls = useRef<string[]>([]);
  useEffect(() => () => urls.current.forEach((url) => URL.revokeObjectURL(url)), []);

  if (target.pair.status === "unavailable") {
    return <p className="text-sm text-text-2">{t("shot_workflow_review_unavailable")}</p>;
  }

  async function open() {
    if (opening) return;
    setOpening(true);
    setLoadError(null);
    try {
      const opened = await openReview(projectName, target.target_ref.target_id);
      const reviewed: ReviewedFrame[] = [];
      for (const frame of opened.frames) {
        const delivered = await fetchReviewFrame(projectName, opened.session_id, frame.role);
        const digest = await sha256Digest(delivered.bytes);
        const blob = new Blob([delivered.bytes], { type: "image/png" });
        const url = URL.createObjectURL(blob);
        urls.current.push(url);
        // Only bytes that hash to the reviewed frame and decode as an image can be acknowledged, and only
        // after the reviewer has seen them and confirms it.
        await createImageBitmap(blob);
        const verified = digest === frame.png_digest && digest === delivered.pngDigest;
        reviewed.push({
          sessionId: opened.session_id,
          role: frame.role,
          url,
          verified,
          attemptId: delivered.attemptId,
          pngDigest: digest,
          acknowledged: false,
        });
      }
      setSnapshot(opened);
      setFrames(reviewed);
    } catch (caught) {
      setLoadError(errorMessage(caught) ?? t("shot_workflow_action_failed"));
    } finally {
      setOpening(false);
    }
  }

  if (!snapshot) {
    return (
      <div>
        <button type="button" disabled={opening} onClick={() => void open()} className="sp-btn-accent sw-primary">
          {t("shot_workflow_review_open")}
        </button>
        <StepError error={loadError} />
      </div>
    );
  }

  const allVerified = frames.length === 2 && frames.every((frame) => frame.verified && frame.acknowledged);
  function confirm(role: ReviewRole) {
    const frame = frames.find((item) => item.role === role);
    if (!snapshot || !frame?.verified || frame.acknowledged) return;
    void run(async (signal) => {
      await acknowledgeFrame(
        projectName,
        snapshot.session_id,
        { attemptId: frame.attemptId, role, pngDigest: frame.pngDigest },
        { signal },
      );
      // Mark only the exact delivered frame of this session, never a frame a later review replaced it with.
      setFrames((current) =>
        current.map((item) =>
          item.sessionId === frame.sessionId && item.attemptId === frame.attemptId
            ? { ...item, acknowledged: true }
            : item,
        ),
      );
    }, false);
  }
  const approveReady = allVerified && [notes.view_coverage, notes.camera_center, notes.yaw_relation].every((v) => v.trim());
  function decide(decision: "APPROVE" | "REJECT") {
    const observations: PairObservations =
      decision === "APPROVE"
        ? {
            view_coverage: notes.view_coverage.trim(),
            camera_center: notes.camera_center.trim(),
            yaw_relation: notes.yaw_relation.trim(),
            rejection_reason: null,
          }
        : { view_coverage: null, camera_center: null, yaw_relation: null, rejection_reason: notes.rejection_reason.trim() };
    void run(async (signal) => {
      await decidePair(projectName, snapshot!, decision, observations, { signal });
    });
  }

  return (
    <div>
      <div className="sp-pair">
        {frames.map((frame) => (
          <figure key={frame.role} className="sp-slot rounded-md border border-hairline-strong bg-bg p-2">
            <figcaption className="font-mono text-[10px] tracking-[0.18em] text-text-3">
              {frame.role} · {frame.verified ? t("shot_workflow_review_verified") : t("shot_workflow_review_mismatch")}
            </figcaption>
            <img src={frame.url} alt={t("shot_workflow_review_frame_alt", { role: frame.role })} className="mt-2 w-full rounded" />
            {frame.verified ? (
              <button
                type="button"
                disabled={busy || frame.acknowledged}
                aria-pressed={frame.acknowledged}
                onClick={() => confirm(frame.role)}
                className="sw-btn mt-2"
              >
                {frame.acknowledged
                  ? t("shot_workflow_review_confirmed", { role: frame.role })
                  : t("shot_workflow_review_confirm", { role: frame.role })}
              </button>
            ) : null}
          </figure>
        ))}
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {(["view_coverage", "camera_center", "yaw_relation"] as const).map((field) => (
          <label key={field} className="block text-xs text-text-2">
            {t(`shot_workflow_obs_${field}`)}
            <input
              value={notes[field]}
              maxLength={500}
              disabled={busy}
              onChange={(event) => setNotes((current) => ({ ...current, [field]: event.target.value }))}
              className="sw-input mt-1"
            />
          </label>
        ))}
      </div>
      <label className="mt-3 block text-xs text-text-2">
        {t("shot_workflow_obs_rejection_reason")}
        <input
          value={notes.rejection_reason}
          maxLength={500}
          disabled={busy}
          onChange={(event) => setNotes((current) => ({ ...current, rejection_reason: event.target.value }))}
          className="sw-input mt-1"
        />
      </label>
      <div className="mt-4 flex flex-wrap gap-3">
        <button type="button" disabled={busy || !approveReady} onClick={() => decide("APPROVE")} className="sp-btn-accent sw-primary">
          {t("shot_workflow_review_approve")}
        </button>
        <button
          type="button"
          disabled={busy || !allVerified || !notes.rejection_reason.trim()}
          onClick={() => decide("REJECT")}
          className="sw-btn"
        >
          {t("shot_workflow_review_reject")}
        </button>
      </div>
      <StepError error={error} />
    </div>
  );
}

function AnalyzeStep({ projectName, episode, target, onChanged }: PanelProps) {
  const { t } = useTranslation("dashboard");
  const { busy, error, run } = useStepAction(onChanged);
  const bindingVersion = target.pair.binding_version ?? 0;
  return (
    <div>
      <button
        type="button"
        disabled={busy}
        onClick={() =>
          void run(async (signal) => {
            const [master, reverse] = target.pair.views;
            if (!master || !reverse) return;
            const candidateId = workflowCandidateId(target.target_ref.target_id, bindingVersion);
            await executeSpatial(
              projectName,
              {
                commandId: `analyze:${candidateId}`,
                candidateId,
                episode,
                sceneName: (target.location_ref ?? target.target_ref.target_id).slice(0, 120),
                master: { receipt_id: master.receipt_id, receipt_digest: master.receipt_digest },
                reverse: { receipt_id: reverse.receipt_id, receipt_digest: reverse.receipt_digest },
              },
              { signal },
            );
          })
        }
        className="sp-btn-accent sw-primary"
      >
        {busy ? t("spatial_analyzing") : t("spatial_analyze")}
      </button>
      <StepError error={error} />
    </div>
  );
}

function PromoteStep({ projectName, target, head, onChanged }: PanelProps) {
  const { t } = useTranslation("dashboard");
  const { busy, error, run } = useStepAction(onChanged);
  const [assertions, setAssertions] = useState<SpatialAssertion[] | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!head) return;
    const controller = new AbortController();
    getSpatialRevision(projectName, head, { signal: controller.signal }).then(
      (revision) => {
        if (controller.signal.aborted) return;
        const visible = revision.payload.spatial.assertions.filter((item) => item.evidence_class === "VISIBLE");
        setAssertions(visible);
        setChosen(new Set(visible.map((item) => item.assertion_id)));
      },
      () => undefined,
    );
    return () => controller.abort();
  }, [projectName, head]);

  if (!head || assertions === null) return <p className="text-xs text-text-3">{t("shot_workflow_loading")}</p>;
  if (assertions.length === 0) return <p className="text-sm text-text-2">{t("shot_workflow_promote_empty")}</p>;
  return (
    <div>
      <fieldset>
        <legend className="text-xs text-text-2">{t("shot_workflow_promote_pick")}</legend>
        <ul className="mt-2 space-y-2">
          {assertions.map((item) => (
            <li key={item.assertion_id}>
              <label className="sp-finding sp-finding-visible flex items-start gap-2 rounded-md p-3 text-sm text-text">
                <input
                  type="checkbox"
                  checked={chosen.has(item.assertion_id)}
                  disabled={busy}
                  onChange={(event) =>
                    setChosen((current) => {
                      const next = new Set(current);
                      if (event.target.checked) next.add(item.assertion_id);
                      else next.delete(item.assertion_id);
                      return next;
                    })
                  }
                  className="mt-1"
                />
                {item.relation}
              </label>
            </li>
          ))}
        </ul>
      </fieldset>
      <button
        type="button"
        disabled={busy || chosen.size === 0}
        onClick={() =>
          void run(async (signal) => {
            const selected = assertions.filter((item) => chosen.has(item.assertion_id)).map((item) => item.assertion_id);
            const preview = await previewPromotion(
              projectName,
              {
                commandId: `preview:${crypto.randomUUID()}`,
                candidateId: head.candidate_id,
                revision: head.current_revision,
                targetId: target.target_ref.target_id,
                bindingVersion: target.binding.binding_version ?? 0,
                assertionIds: selected,
              },
              { signal },
            );
            await promote(projectName, preview, head.head_version, { signal });
          })
        }
        className="sp-btn-accent sw-primary mt-4"
      >
        {t("shot_workflow_promote_action", { count: chosen.size })}
      </button>
      <StepError error={error} />
    </div>
  );
}

function GenerateStep({ projectName, target, onChanged }: PanelProps) {
  const { t } = useTranslation("dashboard");
  const { busy, error, run } = useStepAction(onChanged);
  const id = target.target_ref.target_id;
  const inFlight = target.shot !== null && !RETRYABLE_SHOT.has(target.shot.status);
  const { binding } = target;
  return (
    <div>
      {inFlight ? <p className="text-sm text-text-2">{t("shot_workflow_generate_running", { status: target.shot?.status })}</p> : null}
      {target.shot && RETRYABLE_SHOT.has(target.shot.status) ? (
        <p className="text-sm text-warn">{t("shot_workflow_generate_failed")}</p>
      ) : null}
      {inFlight ? (
        <button type="button" onClick={onChanged} className="sw-btn mt-3">
          {t("shot_workflow_refresh")}
        </button>
      ) : (
      <button
        type="button"
        disabled={busy || binding.snapshot_digest === null}
        onClick={() =>
          void run(async () => {
            if (isResourceBusy("r2_shot_generation_v1", projectName, id)) return;
            await enqueueR2Shot(projectName, id, {
              command_id: `generate:${id}:${binding.snapshot_digest}:${target.shot?.task_id ?? "first"}`,
              expected_target_registry_version: binding.target_registry_version ?? 0,
              expected_binding_snapshot_digest: binding.snapshot_digest ?? "",
              execution_profile_ref: SHOT_PROFILE_REF,
            });
          })
        }
        className="sp-btn-accent sw-primary mt-3"
      >
        {t("shot_workflow_generate_action")}
      </button>
      )}
      <StepError error={error} />
    </div>
  );
}

function ApproveStep({ projectName, target, onChanged }: PanelProps) {
  const { t } = useTranslation("dashboard");
  const { busy, error, run } = useStepAction(onChanged);
  const [record, setRecord] = useState("");
  const taskId = target.shot?.task_id ?? "";
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!record.trim()) return;
        void run(async (signal) => {
          await approveShot(projectName, target.target_ref.target_id, { taskId, approvalRecord: record.trim() }, { signal });
        });
      }}
    >
      <label className="block max-w-md text-xs text-text-2">
        {t("shot_workflow_approve_record")}
        <input value={record} maxLength={255} disabled={busy} onChange={(event) => setRecord(event.target.value)} className="sw-input mt-1" />
      </label>
      <button type="submit" disabled={busy || !record.trim()} className="sp-btn-accent sw-primary mt-4">
        {t("shot_workflow_approve_action")}
      </button>
      <StepError error={error} />
    </form>
  );
}
