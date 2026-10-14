/**
 * The format projections of a project (route `formats`): plan a 16:9, 9:16 or 1:1 projection of an
 * approved video master, render it, check it technically, review it blind against the source, and
 * approve its promotion into the projection's own master slot. Each step uses the server's verdicts;
 * nothing here decides whether a projection is acceptable.
 */
import "./formats.css";

import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import {
  approvePromotion,
  boxFromPercent,
  boxValue,
  createPlan,
  ensureStandardProfiles,
  listPlans,
  listSources,
  openReview,
  prepareCandidate,
  previewPromotion,
  renderPlan,
  reviewClip,
  STANDARD_PROFILES,
  NO_OVERLAY,
  submitReview,
  validateRender,
  type FormatPreview,
  type FormatSource,
  type PlanSummary,
  type PreparedCandidate,
  type ReframeKind,
  type ReviewPacket,
  type Verdict,
} from "../api/formatClient";

function errorMessage(error: unknown): string | null {
  return error instanceof Error && error.message ? error.message : null;
}

/** One abortable operation at a time; leaving the component aborts it, so no state is written after. */
function useOperation(): () => AbortSignal {
  const current = useRef<AbortController | null>(null);
  useEffect(() => () => current.current?.abort(), []);
  return useCallback(() => {
    current.current?.abort();
    current.current = new AbortController();
    return current.current.signal;
  }, []);
}

/** Runs one async step with busy and error state that never outlive the component. */
function useStep() {
  const begin = useOperation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(
    async <T,>(step: (signal: AbortSignal) => Promise<T>, fallback: string): Promise<T | null> => {
      const signal = begin();
      setBusy(true);
      setError(null);
      try {
        const result = await step(signal);
        return signal.aborted ? null : result;
      } catch (failure: unknown) {
        if (!signal.aborted) setError(errorMessage(failure) ?? fallback);
        return null;
      } finally {
        if (!signal.aborted) setBusy(false);
      }
    },
    [begin],
  );
  return { busy, error, run };
}

interface FormatsPageProps {
  projectName: string;
}

export default function FormatsPage({ projectName }: FormatsPageProps) {
  const { t } = useTranslation("dashboard");
  const [sources, setSources] = useState<FormatSource[] | null>(null);
  const [plans, setPlans] = useState<PlanSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const reload = useCallback(() => setReloadToken((token) => token + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      listSources(projectName, { signal: controller.signal }),
      listPlans(projectName, { signal: controller.signal }),
    ]).then(
      ([foundSources, foundPlans]) => {
        if (controller.signal.aborted) return;
        setSources(foundSources);
        setPlans(foundPlans);
        setLoadError(null);
      },
      (error: unknown) => {
        if (!controller.signal.aborted) setLoadError(errorMessage(error) ?? t("formats_load_failed"));
      },
    );
    return () => controller.abort();
  }, [projectName, reloadToken, t]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-bg">
      <header className="fm-header border-b border-hairline py-2.5">
        <p className="font-mono text-[10px] tracking-[0.18em] text-text-3">PROJECT · FORMATS</p>
        <h1 className="font-editorial text-xl leading-tight text-text">{t("formats_title")}</h1>
        <p className="mt-0.5 max-w-2xl text-xs text-text-2">{t("formats_subtitle")}</p>
      </header>

      <div className="fm-layout mx-auto w-full max-w-6xl px-4 py-6">
        {loadError ? (
          <div role="alert" className="rounded-md border border-hairline-strong p-4 text-sm text-text-2">
            {loadError}
            <button type="button" onClick={reload} className="fm-btn ml-3">
              {t("spatial_retry")}
            </button>
          </div>
        ) : sources === null || plans === null ? (
          <p role="status" className="text-sm text-text-3">
            {t("formats_loading")}
          </p>
        ) : (
          <>
            <NewPlan projectName={projectName} sources={sources} onCreated={reload} />
            <section aria-labelledby="fm-plans-title" className="min-w-0">
              <h2 id="fm-plans-title" className="mb-3 font-mono text-[11px] tracking-[0.14em] text-text-3">
                PROJECTIONS
              </h2>
              {plans.length === 0 ? (
                <p className="rounded-md border border-dashed border-hairline-strong p-4 text-sm text-text-2">
                  {t("formats_empty")}
                </p>
              ) : (
                <ul className="space-y-4">
                  {plans.map((summary) => (
                    <li key={summary.plan.plan_id}>
                      <PlanCard projectName={projectName} summary={summary} onChanged={reload} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}

const KINDS: ReframeKind[] = ["PAD", "COVER_CENTER", "COVER_FOCAL"];

function NewPlan({ projectName, sources, onCreated }: { projectName: string; sources: FormatSource[]; onCreated: () => void }) {
  const { t } = useTranslation("dashboard");
  const ids = { source: useId(), profile: useId(), kind: useId(), rationale: useId() };
  const [source, setSource] = useState(sources[0]?.artifact_key ?? "");
  const [profileRef, setProfileRef] = useState(STANDARD_PROFILES[1].profile_ref);
  const [kind, setKind] = useState<ReframeKind>("PAD");
  const [subject, setSubject] = useState({ x0: 35, y0: 20, x1: 65, y1: 80 });
  const [rationale, setRationale] = useState("");
  const { busy, error, run } = useStep();

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !source || !rationale.trim()) return;
    const box = boxFromPercent(subject.x0, subject.y0, subject.x1, subject.y1);
    const created = await run(async (signal) => {
      await ensureStandardProfiles(projectName, { signal });
      return createPlan(
        projectName,
        {
          plan_id: `${profileRef.split("@")[0]}-${kind.toLowerCase()}-${crypto.randomUUID().slice(0, 8)}`,
          source_artifact_key: source,
          profile_ref: profileRef,
          constraint_ref: NO_OVERLAY.constraint_ref,
          kind,
          focal: kind === "COVER_FOCAL" ? box : null,
          subject: box,
          captions: [],
          rationale: rationale.trim(),
        },
        { signal },
      );
    }, t("formats_plan_failed"));
    if (created) {
      setRationale("");
      onCreated();
    }
  }

  if (sources.length === 0) {
    return (
      <section className="fm-new rounded-md border border-dashed border-hairline-strong p-4 text-sm text-text-2">
        {t("formats_no_sources")}
      </section>
    );
  }

  return (
    <section aria-labelledby="fm-new-title" className="fm-new rounded-md border border-hairline p-4">
      <h2 id="fm-new-title" className="font-editorial text-base text-text">
        {t("formats_new_title")}
      </h2>
      <p className="mt-1 text-xs text-text-2">{t("formats_new_hint")}</p>
      <form onSubmit={(event) => void submit(event)} className="mt-3 space-y-3">
        <fieldset disabled={busy} className="space-y-3">
          <legend className="sr-only">{t("formats_new_title")}</legend>
          <div>
            <label htmlFor={ids.source} className="block text-[11px] text-text-3">
              {t("formats_field_source")}
            </label>
            <select id={ids.source} value={source} onChange={(event) => setSource(event.target.value)} className="fm-input">
              {sources.map((item) => (
                <option key={item.artifact_key} value={item.artifact_key}>
                  {item.label} · v{item.master_version}
                </option>
              ))}
            </select>
          </div>
          <div className="fm-grid">
            <div>
              <label htmlFor={ids.profile} className="block text-[11px] text-text-3">
                {t("formats_field_profile")}
              </label>
              <select id={ids.profile} value={profileRef} onChange={(event) => setProfileRef(event.target.value)} className="fm-input">
                {STANDARD_PROFILES.map((profile) => (
                  <option key={profile.profile_ref} value={profile.profile_ref}>
                    {profile.width}×{profile.height}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor={ids.kind} className="block text-[11px] text-text-3">
                {t("formats_field_kind")}
              </label>
              <select id={ids.kind} value={kind} onChange={(event) => setKind(event.target.value as ReframeKind)} className="fm-input">
                {KINDS.map((item) => (
                  <option key={item} value={item}>
                    {t(`formats_kind_${item}`)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <fieldset className="fm-grid">
            <legend className="text-[11px] text-text-3">{t("formats_field_subject")}</legend>
            {(["x0", "y0", "x1", "y1"] as const).map((edge) => (
              <PercentInput
                key={edge}
                label={t(`formats_subject_${edge}`)}
                value={subject[edge]}
                onChange={(value) => setSubject({ ...subject, [edge]: value })}
              />
            ))}
          </fieldset>
          <div>
            <label htmlFor={ids.rationale} className="block text-[11px] text-text-3">
              {t("formats_field_rationale")}
            </label>
            <textarea
              id={ids.rationale}
              required
              rows={2}
              value={rationale}
              onChange={(event) => setRationale(event.target.value)}
              className="fm-input"
            />
          </div>
        </fieldset>
        <button type="submit" disabled={busy || !rationale.trim()} className="fm-btn fm-btn-accent">
          {busy ? t("formats_planning") : t("formats_plan")}
        </button>
        {error ? (
          <p role="alert" className="text-sm text-text-2">
            {error}
          </p>
        ) : null}
      </form>
    </section>
  );
}

function PercentInput({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block text-[11px] text-text-3">
        {label}
      </label>
      <input
        id={id}
        type="number"
        min={0}
        max={100}
        step={1}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="fm-input"
      />
    </div>
  );
}

/** The source frame, what the projection keeps of it, and where the subject lands. */
function ReframeDiagram({ summary }: { summary: PlanSummary }) {
  const { t } = useTranslation("dashboard");
  const decision = summary.plan.reframe_decisions[0];
  const source = decision.source_span;
  const window = boxValue(source);
  const width = Number(source.width);
  const height = Number(source.height);
  const subject = source.subject ? boxValue(source.subject as Record<string, unknown>) : null;
  const scale = 160 / Math.max(width, height);
  const w = width * scale;
  const h = height * scale;
  return (
    <svg
      className="fm-diagram"
      viewBox={`-4 -4 ${w + 8} ${h + 8}`}
      role="img"
      aria-label={t("formats_diagram_label", {
        kept: Math.round((window.x1 - window.x0) * (window.y1 - window.y0) * 100),
      })}
    >
      <rect x={0} y={0} width={w} height={h} className="fm-diagram-source" />
      <rect
        x={window.x0 * w}
        y={window.y0 * h}
        width={(window.x1 - window.x0) * w}
        height={(window.y1 - window.y0) * h}
        className="fm-diagram-window"
      />
      {subject ? (
        <rect
          x={subject.x0 * w}
          y={subject.y0 * h}
          width={(subject.x1 - subject.x0) * w}
          height={(subject.y1 - subject.y0) * h}
          className="fm-diagram-subject"
        />
      ) : null}
    </svg>
  );
}

function PlanCard({ projectName, summary, onChanged }: { projectName: string; summary: PlanSummary; onChanged: () => void }) {
  const { t } = useTranslation("dashboard");
  const plan = summary.plan;
  const decision = plan.reframe_decisions[0];
  const latest = summary.renders[0] ?? null;
  const technical = latest && summary.technical?.artifact_digest === latest.artifact_digest ? summary.technical : null;
  const semantic = latest && summary.semantic?.artifact_digest === latest.artifact_digest ? summary.semantic : null;
  const { busy, error, run } = useStep();
  const [reviewing, setReviewing] = useState(false);
  const [candidate, setCandidate] = useState<PreparedCandidate | null>(null);

  async function prepare() {
    if (!latest) return;
    const prepared = await run((signal) => prepareCandidate(projectName, latest.execution_id, { signal }), t("formats_candidate_failed"));
    if (prepared) setCandidate(prepared);
  }

  async function step<T>(action: (signal: AbortSignal) => Promise<T>, fallback: string) {
    const result = await run(action, fallback);
    if (result !== null) onChanged();
    return result;
  }

  return (
    <article className="fm-card rounded-md border border-hairline p-4" aria-labelledby={`fm-${plan.plan_id}`}>
      <div className="fm-card-head">
        <ReframeDiagram summary={summary} />
        <div className="min-w-0">
          <p className="font-mono text-[10px] tracking-[0.12em] text-text-3">
            {plan.output_profile.width}×{plan.output_profile.height} · {t(`formats_kind_${decision.kind}`)}
          </p>
          <h3 id={`fm-${plan.plan_id}`} className="font-editorial text-base text-text">
            {plan.plan_id}
          </h3>
          <p className="text-xs text-text-2">{decision.rationale}</p>
          <p className={`fm-risk fm-risk-${decision.semantic_risk.toLowerCase()}`}>
            {t(`formats_risk_${decision.semantic_risk}`)}
          </p>
        </div>
      </div>

      <ol className="fm-steps mt-3" aria-label={t("formats_steps_label")}>
        <li>
          <span>{t("formats_step_render")}</span>
          <span className="fm-state">{latest ? t("formats_done") : t("formats_pending")}</span>
          <button
            type="button"
            className="fm-btn"
            disabled={busy}
            onClick={() => void step((signal) => renderPlan(projectName, plan.plan_id, crypto.randomUUID(), { signal }), t("formats_render_failed"))}
          >
            {latest ? t("formats_render_again") : t("formats_render")}
          </button>
        </li>
        <li>
          <span>{t("formats_step_check")}</span>
          <span className="fm-state">
            {technical ? (technical.passed ? t("formats_passed") : t("formats_failed")) : t("formats_pending")}
          </span>
          <button
            type="button"
            className="fm-btn"
            disabled={busy || !latest}
            onClick={() =>
              latest && void step((signal) => validateRender(projectName, latest.execution_id, { signal }), t("formats_check_failed"))
            }
          >
            {t("formats_check")}
          </button>
        </li>
        <li>
          <span>{t("formats_step_review")}</span>
          <span className="fm-state">
            {semantic ? (semantic.passed ? t("formats_passed") : t("formats_failed")) : t("formats_pending")}
          </span>
          <button type="button" className="fm-btn" disabled={busy || !latest} onClick={() => setReviewing(true)}>
            {t("formats_review")}
          </button>
        </li>
        <li>
          <span>{t("formats_step_promote")}</span>
          <span className="fm-state">{candidate ? t("formats_ready") : t("formats_pending")}</span>
          <button
            type="button"
            className="fm-btn"
            disabled={busy || !latest || !technical?.passed || !semantic?.passed}
            onClick={() => void prepare()}
          >
            {t("formats_prepare")}
          </button>
        </li>
      </ol>

      {technical ? (
        <table className="fm-checks mt-3 text-[11px]">
          <caption className="sr-only">{t("formats_checks_caption")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("formats_check_name")}</th>
              <th scope="col">{t("formats_check_observed")}</th>
              <th scope="col">{t("formats_check_expected")}</th>
              <th scope="col">{t("formats_check_verdict")}</th>
            </tr>
          </thead>
          <tbody>
            {technical.checks.map((check) => (
              <tr key={check.name} className={check.verdict === "FAIL" ? "fm-fail" : undefined}>
                <th scope="row">{t(`formats_check_${check.name}`)}</th>
                <td>{JSON.stringify(check.observed)}</td>
                <td>{JSON.stringify(check.expected)}</td>
                <td>{check.verdict === "PASS" ? t("formats_passed") : t("formats_failed")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {error ? (
        <p role="alert" className="mt-2 text-sm text-text-2">
          {error}
        </p>
      ) : null}

      {reviewing && latest ? (
        <BlindReview
          projectName={projectName}
          executionId={latest.execution_id}
          onClose={() => setReviewing(false)}
          onSubmitted={() => {
            setReviewing(false);
            onChanged();
          }}
        />
      ) : null}
      {candidate ? <Promotion projectName={projectName} candidate={candidate} onPromoted={onChanged} /> : null}
    </article>
  );
}

/** Two clips, A and B, in an order only the server knows; the reviewer judges whether they mean the same. */
function BlindReview({
  projectName,
  executionId,
  onClose,
  onSubmitted,
}: {
  projectName: string;
  executionId: string;
  onClose: () => void;
  onSubmitted: () => void;
}) {
  const { t } = useTranslation("dashboard");
  const [packet, setPacket] = useState<ReviewPacket | null>(null);
  const [clips, setClips] = useState<{ A: string; B: string } | null>(null);
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({});
  const [note, setNote] = useState("");
  const [openError, setOpenError] = useState<string | null>(null);
  const noteId = useId();
  const { busy, error, run } = useStep();

  useEffect(() => {
    const controller = new AbortController();
    const urls: string[] = [];
    void (async () => {
      try {
        const found = await openReview(projectName, executionId, { signal: controller.signal });
        const a = await reviewClip(projectName, found.packet_id, "A", { signal: controller.signal });
        urls.push(a);
        const b = await reviewClip(projectName, found.packet_id, "B", { signal: controller.signal });
        urls.push(b);
        if (controller.signal.aborted) return;
        setPacket(found);
        setClips({ A: a, B: b });
      } catch (failure: unknown) {
        if (!controller.signal.aborted) setOpenError(errorMessage(failure) ?? t("formats_review_open_failed"));
      }
    })();
    return () => {
      controller.abort();
      urls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [projectName, executionId, t]);

  const complete = packet !== null && packet.items.every((item) => verdicts[item]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!packet || !complete || busy) return;
    const report = await run((signal) => submitReview(projectName, packet.packet_id, verdicts, note.trim(), { signal }), t("formats_review_failed"));
    if (report) onSubmitted();
  }

  return (
    <section className="fm-review mt-4 rounded-md border border-hairline-strong p-3" aria-label={t("formats_review_title")}>
      <div className="flex items-center justify-between gap-2">
        <h4 className="font-editorial text-sm text-text">{t("formats_review_title")}</h4>
        <button type="button" className="fm-btn" onClick={onClose}>
          {t("formats_close")}
        </button>
      </div>
      <p className="mt-1 text-xs text-text-2">{t("formats_review_hint")}</p>
      {openError ? (
        <p role="alert" className="mt-3 text-sm text-text-2">
          {openError}
        </p>
      ) : clips ? (
        <div className="fm-lighttable mt-3">
          {(["A", "B"] as const).map((label) => (
            <figure key={label}>
              {/* eslint-disable-next-line jsx-a11y/media-has-caption -- the review compares the rendered media itself; captions are one of the judged items */}
              <video src={clips[label]} controls preload="metadata" className="fm-clip" aria-label={t("formats_clip_label", { label })} />
              <figcaption className="font-mono text-[10px] tracking-[0.14em] text-text-3">CLIP {label}</figcaption>
            </figure>
          ))}
        </div>
      ) : (
        <p role="status" className="mt-3 text-xs text-text-3">
          {t("formats_review_loading")}
        </p>
      )}
      {packet ? (
        <form onSubmit={(event) => void submit(event)} className="mt-3 space-y-2">
          <fieldset disabled={busy} className="space-y-1">
            <legend className="text-[11px] text-text-3">{t("formats_rubric_legend")}</legend>
            {packet.items.map((item) => (
              <div key={item} className="fm-rubric" role="radiogroup" aria-label={t(`formats_item_${item}`)}>
                <span className="text-xs text-text">{t(`formats_item_${item}`)}</span>
                {(["PASS", "FAIL"] as const).map((verdict) => (
                  <label key={verdict} className="fm-choice">
                    <input
                      type="radio"
                      name={`${packet.packet_id}-${item}`}
                      checked={verdicts[item] === verdict}
                      onChange={() => setVerdicts({ ...verdicts, [item]: verdict })}
                    />
                    <span>{verdict === "PASS" ? t("formats_same") : t("formats_changed")}</span>
                  </label>
                ))}
              </div>
            ))}
            <label htmlFor={noteId} className="mt-2 block text-[11px] text-text-3">
              {t("formats_review_note")}
            </label>
            <textarea id={noteId} rows={2} value={note} onChange={(event) => setNote(event.target.value)} className="fm-input" />
          </fieldset>
          <button type="submit" disabled={busy || !complete} className="fm-btn fm-btn-accent">
            {busy ? t("formats_submitting") : t("formats_submit_review")}
          </button>
        </form>
      ) : null}
      {error ? (
        <p role="alert" className="mt-2 text-sm text-text-2">
          {error}
        </p>
      ) : null}
    </section>
  );
}

function Promotion({ projectName, candidate, onPromoted }: { projectName: string; candidate: PreparedCandidate; onPromoted: () => void }) {
  const { t } = useTranslation("dashboard");
  const [preview, setPreview] = useState<FormatPreview | null>(null);
  const [promoted, setPromoted] = useState(false);
  const { busy, error, run } = useStep();

  async function showPreview() {
    const found = await run(
      (signal) => previewPromotion(projectName, candidate, crypto.randomUUID(), { signal }),
      t("formats_preview_failed"),
    );
    if (found) setPreview(found);
  }

  async function approve(shown: FormatPreview) {
    const receipt = await run(
      (signal) => approvePromotion(projectName, shown, candidate.head_version, crypto.randomUUID(), { signal }),
      t("formats_promotion_failed"),
    );
    if (receipt) {
      setPromoted(true);
      onPromoted();
    }
  }

  return (
    <section className="fm-promotion mt-4 rounded-md border border-hairline p-3" aria-label={t("formats_promotion_title")}>
      <h4 className="font-editorial text-sm text-text">{t("formats_promotion_title")}</h4>
      <p className="mt-1 text-xs text-text-2">
        {candidate.expected_target_version === 0 ? t("formats_promotion_first") : t("formats_promotion_replace", { version: candidate.expected_target_version })}
      </p>
      {promoted ? (
        <p role="status" className="mt-2 text-sm text-text">
          {t("formats_promoted")}
        </p>
      ) : preview ? (
        <button
          type="button"
          className="fm-btn fm-btn-accent mt-2"
          disabled={busy}
          onClick={() => void approve(preview)}
        >
          {t("formats_approve")}
        </button>
      ) : (
        <button
          type="button"
          className="fm-btn mt-2"
          disabled={busy}
          onClick={() => void showPreview()}
        >
          {t("formats_preview")}
        </button>
      )}
      {error ? (
        <p role="alert" className="mt-2 text-sm text-text-2">
          {error}
        </p>
      ) : null}
    </section>
  );
}
