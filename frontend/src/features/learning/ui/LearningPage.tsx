/**
 * The learning page of a project (route `learning`): run the cohort comparison over the project's
 * current observations, read each proposed recommendation with its evidence, and record a Human
 * decision. Recommendations are proposals; accepting one records a governed proposal reference and
 * changes nothing in the project.
 */
import "./learning.css";

import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import {
  decideRecommendation,
  DISPOSITIONS,
  evaluateRule,
  listRecommendations,
  relativeLift,
  type ArmSummary,
  type Disposition,
  type EvaluateRequest,
  type EvaluateResponse,
  type RecommendationView,
} from "../api/learningClient";

const RULE_REASONS: Record<string, string> = {
  "no observations": "learning_reason_no_observations",
  "both arms need observations": "learning_reason_missing_arm",
  "insufficient present values": "learning_reason_insufficient",
  "lift below threshold": "learning_reason_below_threshold",
  "baseline mean is zero": "learning_reason_zero_baseline",
  "lift at or above threshold": "learning_reason_fired",
  replayed: "learning_reason_replayed",
};

const DEFAULT_REQUEST: Omit<EvaluateRequest, "command_id"> = {
  source_family: "youtube.analytics.v2",
  metric_name: "views",
  metric_definition_version: "youtube.analytics.v2/views@1",
  aggregation: "sum_day",
  creative_profile_id: "arcreel.host",
  creative_profile_version: "1",
  arm_a: "16x9",
  arm_b: "9x16",
  min_per_arm: 3,
  min_relative_lift: "0.10",
  expires_in_days: 30,
};

function errorMessage(error: unknown): string | null {
  return error instanceof Error && error.message ? error.message : null;
}

function percent(value: number | null): string {
  if (value === null) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value * 100).toFixed(1)}%`;
}

function amount(value: string | null, locale: string): string {
  if (value === null) return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString(locale, { maximumFractionDigits: 2 }) : value;
}

function when(value: string, locale: string): string {
  return new Date(value).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
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

interface LearningPageProps {
  projectName: string;
}

export default function LearningPage({ projectName }: LearningPageProps) {
  const { t } = useTranslation("dashboard");
  const [views, setViews] = useState<RecommendationView[] | null>(null);
  const [loadedAt, setLoadedAt] = useState(0);
  const [listError, setListError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const reload = useCallback(() => setReloadToken((token) => token + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    listRecommendations(projectName, { signal: controller.signal }).then(
      (listed) => {
        if (controller.signal.aborted) return;
        setViews(listed);
        setLoadedAt(Date.now());
        setListError(null);
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setListError(errorMessage(error) ?? t("learning_load_failed"));
      },
    );
    return () => controller.abort();
  }, [projectName, reloadToken, t]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-bg">
      <header className="lr-header border-b border-hairline py-2.5">
        <p className="font-mono text-[10px] tracking-[0.18em] text-text-3">PROJECT · LEARNING</p>
        <h1 className="font-editorial text-xl leading-tight text-text">{t("learning_title")}</h1>
        <p className="mt-0.5 max-w-2xl text-xs text-text-2">{t("learning_subtitle")}</p>
      </header>

      <div className="lr-layout mx-auto w-full max-w-6xl px-4 py-6">
        <EvaluatePanel projectName={projectName} onProposed={reload} />

        <section aria-labelledby="lr-list-title" className="min-w-0">
          <h2 id="lr-list-title" className="mb-3 font-mono text-[11px] tracking-[0.14em] text-text-3">
            RECOMMENDATIONS
          </h2>
          {listError ? (
            <div role="alert" className="rounded-md border border-hairline-strong p-4 text-sm text-text-2">
              {listError}
              <button type="button" onClick={reload} className="lr-btn ml-3">
                {t("spatial_retry")}
              </button>
            </div>
          ) : views === null ? (
            <p role="status" className="text-sm text-text-3">
              {t("learning_loading")}
            </p>
          ) : views.length === 0 ? (
            <p className="rounded-md border border-dashed border-hairline-strong p-4 text-sm text-text-2">
              {t("learning_empty")}
            </p>
          ) : (
            <ul className="space-y-4">
              {views.map((view) => (
                <li key={view.recommendation.recommendation_id}>
                  <RecommendationCard projectName={projectName} view={view} now={loadedAt} onDecided={reload} />
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const id = useId();
  return (
    <div className="lr-field">
      <label htmlFor={id} className="block text-[11px] text-text-3">
        {label}
      </label>
      <input id={id} required value={value} onChange={(event) => onChange(event.target.value)} className="lr-input" />
    </div>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  const id = useId();
  return (
    <div className="lr-field">
      <label htmlFor={id} className="block text-[11px] text-text-3">
        {label}
      </label>
      <input
        id={id}
        type="number"
        required
        min={min}
        max={max}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="lr-input"
      />
    </div>
  );
}

function EvaluatePanel({ projectName, onProposed }: { projectName: string; onProposed: () => void }) {
  const { t } = useTranslation("dashboard");
  const [form, setForm] = useState(DEFAULT_REQUEST);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<EvaluateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const begin = useOperation();
  // A result belongs to the inputs that produced it; any edit clears it.
  const edit = (next: typeof form) => {
    setForm(next);
    setResult(null);
    setError(null);
  };

  type TextKey = Exclude<keyof typeof form, "min_per_arm" | "expires_in_days">;
  const text = (key: TextKey, label: string) => (
    <TextField label={label} value={form[key]} onChange={(value) => edit({ ...form, [key]: value })} />
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const signal = begin();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await evaluateRule(projectName, { ...form, command_id: crypto.randomUUID() }, { signal });
      if (signal.aborted) return;
      setResult(response);
      if (response.recommendation) onProposed();
    } catch (failure: unknown) {
      if (signal.aborted) return;
      setError(errorMessage(failure) ?? t("learning_evaluate_failed"));
    } finally {
      if (!signal.aborted) setBusy(false);
    }
  }

  return (
    <section aria-labelledby="lr-evaluate-title" className="lr-evaluate rounded-md border border-hairline p-4">
      <h2 id="lr-evaluate-title" className="font-editorial text-base text-text">
        {t("learning_evaluate_title")}
      </h2>
      <p className="mt-1 text-xs text-text-2">{t("learning_evaluate_hint")}</p>
      <form onSubmit={(event) => void submit(event)} className="mt-3 space-y-3">
        <fieldset className="lr-grid" disabled={busy}>
          <legend className="sr-only">{t("learning_metric_legend")}</legend>
          {text("source_family", t("learning_field_source"))}
          {text("metric_name", t("learning_field_metric"))}
          {text("metric_definition_version", t("learning_field_definition"))}
          {text("aggregation", t("learning_field_aggregation"))}
          {text("creative_profile_id", t("learning_field_profile"))}
          {text("creative_profile_version", t("learning_field_profile_version"))}
        </fieldset>
        <fieldset className="lr-grid" disabled={busy}>
          <legend className="sr-only">{t("learning_rule_legend")}</legend>
          {text("arm_a", t("learning_field_arm_a"))}
          {text("arm_b", t("learning_field_arm_b"))}
          <NumberField
            label={t("learning_field_min_per_arm")}
            value={form.min_per_arm}
            min={2}
            max={100000}
            onChange={(value) => edit({ ...form, min_per_arm: value })}
          />
          {text("min_relative_lift", t("learning_field_min_lift"))}
          <NumberField
            label={t("learning_field_expiry")}
            value={form.expires_in_days}
            min={1}
            max={365}
            onChange={(value) => edit({ ...form, expires_in_days: value })}
          />
        </fieldset>
        <button type="submit" disabled={busy} className="lr-btn lr-btn-accent">
          {busy ? t("learning_evaluating") : t("learning_evaluate")}
        </button>
      </form>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-text-2">
          {error}
        </p>
      ) : null}
      {result ? (
        <div role="status" className="mt-4 border-t border-hairline-soft pt-3">
          <p className="text-sm text-text">
            {result.recommendation ? t("learning_result_proposed") : t("learning_result_quiet")}{" "}
            <span className="text-text-2">{t(RULE_REASONS[result.reason] ?? "learning_reason_other")}</span>
          </p>
          {result.arms.length === 2 ? <ArmLedger arms={result.arms} /> : null}
        </div>
      ) : null}
    </section>
  );
}

/** Arm A and arm B face each other; the signed lift of B over A sits between them. */
function ArmLedger({ arms }: { arms: ArmSummary[] }) {
  const { t, i18n } = useTranslation("dashboard");
  const locale = i18n.language;
  const means = arms.map((arm) => (arm.mean === null ? 0 : Math.abs(Number(arm.mean))));
  const scale = Math.max(...means, 0) || 1;
  const lift = relativeLift(arms);
  return (
    <div className="lr-ledger mt-3" aria-label={t("learning_ledger_label")}>
      {arms.map((arm, index) => (
        <div key={arm.arm ?? index} className={index === 0 ? "lr-arm" : "lr-arm lr-arm-b"}>
          <p className="font-mono text-[10px] tracking-[0.14em] text-text-3">
            {index === 0 ? "ARM A" : "ARM B"} · {arm.arm}
          </p>
          <p className="mt-1 font-mono text-2xl tabular-nums text-text">{amount(arm.mean, locale)}</p>
          <div className="lr-bar" aria-hidden>
            <span style={{ width: `${(means[index] / scale) * 100}%` }} />
          </div>
          <dl className="lr-stats mt-2 text-[11px] text-text-2">
            <dt>{t("learning_stat_present")}</dt>
            <dd>
              {arm.present} / {arm.n}
            </dd>
            <dt>{t("learning_stat_median")}</dt>
            <dd>{amount(arm.median, locale)}</dd>
            <dt>{t("learning_stat_range")}</dt>
            <dd>
              {amount(arm.min, locale)} – {amount(arm.max, locale)}
            </dd>
            {Object.entries(arm.missing).map(([reason, count]) => (
              <div key={reason} className="contents">
                <dt>{t("learning_stat_missing", { reason })}</dt>
                <dd>{count}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
      <p className="lr-lift font-mono text-sm tabular-nums" aria-label={t("learning_lift_label")}>
        {percent(lift)}
      </p>
    </div>
  );
}

function RecommendationCard({
  projectName,
  view,
  now,
  onDecided,
}: {
  projectName: string;
  view: RecommendationView;
  /** When the list was read; expiry is judged against it, and the server rechecks on decision. */
  now: number;
  onDecided: () => void;
}) {
  const { t, i18n } = useTranslation("dashboard");
  const recommendation = view.recommendation;
  const summaries = recommendation.applicability.summaries ?? [];
  const lift = relativeLift(summaries);
  const metric = recommendation.applicability.metric_name;
  const lead =
    summaries.length === 2 && lift !== null && typeof metric === "string"
      ? t(lift >= 0 ? "learning_lead_higher" : "learning_lead_lower", {
          a: summaries[0].arm,
          b: summaries[1].arm,
          metric,
          lift: percent(Math.abs(lift)).replace("+", ""),
        })
      : null;
  const expired = new Date(recommendation.expires_at).getTime() <= now;
  return (
    <article className="lr-card rounded-md border border-hairline p-4" aria-labelledby={`lr-${recommendation.recommendation_id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={view.language === "causal" ? "lr-badge lr-badge-causal" : "lr-badge"}>
          {view.language === "causal" ? t("learning_badge_causal") : t("learning_badge_associative")}
        </span>
        <span className="font-mono text-[10px] tracking-[0.12em] text-text-3">{view.rule}</span>
        {view.final ? (
          <span className="font-mono text-[10px] tracking-[0.12em] text-text-3">· {t("learning_final")}</span>
        ) : null}
      </div>
      <p id={`lr-${recommendation.recommendation_id}`} className="mt-2 font-editorial text-base leading-snug text-text">
        {lead ?? recommendation.hypothesis}
      </p>
      {lead ? (
        <p className="mt-1 font-mono text-[10px] leading-relaxed text-text-3">
          {t("learning_recorded_hypothesis")}: {recommendation.hypothesis}
        </p>
      ) : null}
      <p className="mt-1 text-xs text-text-3">
        {view.language === "causal" ? t("learning_language_causal") : t("learning_language_associative")}
      </p>
      {summaries.length === 2 ? <ArmLedger arms={summaries} /> : null}
      <dl className="lr-meta mt-3 text-xs text-text-2">
        <dt>{t("learning_meta_confidence")}</dt>
        <dd>{Math.round(recommendation.confidence * 100)}%</dd>
        <dt>{t("learning_meta_evidence")}</dt>
        <dd>
          {t("learning_meta_evidence_value", {
            count: recommendation.evidence_observation_ids.length,
            cutoff: when(view.evidence_cutoff, i18n.language),
          })}
        </dd>
        <dt>{t("learning_meta_expires")}</dt>
        <dd>
          {when(recommendation.expires_at, i18n.language)}
          {expired ? ` · ${t("learning_expired")}` : ""}
        </dd>
      </dl>
      {recommendation.exclusions.length > 0 ? (
        <p className="mt-2 text-xs text-text-3">
          {t("learning_exclusions")}: {recommendation.exclusions.join("; ")}
        </p>
      ) : null}
      {view.decisions.length > 0 ? (
        <ol className="mt-3 space-y-1 border-t border-hairline-soft pt-2 text-xs text-text-2">
          {view.decisions.map((decision) => (
            <li key={decision.decision_id}>
              <span className="font-mono text-[11px] text-text">{t(`learning_disposition_${decision.disposition}`)}</span>{" "}
              · {decision.actor_id} · {when(decision.decided_at, i18n.language)} — {decision.reason}
              {decision.governed_proposal_ref ? (
                <span className="block font-mono text-[10px] text-text-3">{decision.governed_proposal_ref}</span>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
      {view.final || expired ? null : <DecisionForm projectName={projectName} view={view} onDecided={onDecided} />}
    </article>
  );
}

function DecisionForm({
  projectName,
  view,
  onDecided,
}: {
  projectName: string;
  view: RecommendationView;
  onDecided: () => void;
}) {
  const { t } = useTranslation("dashboard");
  const reasonId = useId();
  const [disposition, setDisposition] = useState<Disposition | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const begin = useOperation();

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || disposition === null || !reason.trim()) return;
    const signal = begin();
    setBusy(true);
    setError(null);
    try {
      await decideRecommendation(projectName, view, disposition, reason.trim(), crypto.randomUUID(), { signal });
      if (signal.aborted) return;
      setReason("");
      setDisposition(null);
      onDecided();
    } catch (failure: unknown) {
      if (signal.aborted) return;
      setError(errorMessage(failure) ?? t("learning_decide_failed"));
    } finally {
      if (!signal.aborted) setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="mt-3 space-y-2 border-t border-hairline-soft pt-3">
      <fieldset disabled={busy}>
        <legend className="text-[11px] text-text-3">{t("learning_decide_legend")}</legend>
        <div className="mt-1 flex flex-wrap gap-2">
          {DISPOSITIONS.map((item) => (
            <label key={item} className="lr-choice">
              <input
                type="radio"
                name={`decision-${view.recommendation.recommendation_id}`}
                value={item}
                checked={disposition === item}
                onChange={() => setDisposition(item)}
              />
              <span>{t(`learning_disposition_${item}`)}</span>
            </label>
          ))}
        </div>
        <label htmlFor={reasonId} className="mt-2 block text-[11px] text-text-3">
          {t("learning_reason_label")}
        </label>
        <textarea
          id={reasonId}
          required
          rows={2}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="lr-input w-full"
        />
        <p className="text-[11px] text-text-3">{t("learning_accept_note")}</p>
      </fieldset>
      <button type="submit" disabled={busy || disposition === null || !reason.trim()} className="lr-btn">
        {busy ? t("learning_deciding") : t("learning_decide")}
      </button>
      {error ? (
        <p role="alert" className="text-sm text-text-2">
          {error}
        </p>
      ) : null}
    </form>
  );
}
