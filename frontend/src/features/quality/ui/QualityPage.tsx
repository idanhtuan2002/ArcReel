/**
 * Quality review of an approved video (route `quality`): pick the master, publish a quality profile from the
 * template, run the two probes, record the Human review, seal the run and issue the disposition, then open the run
 * in Packaging. Each action is prepared on the server, shown for confirmation and submitted unchanged; nothing here
 * decides whether a video passes.
 */
import "../../formats/ui/formats.css";
import "../../packaging/ui/packaging.css";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  listMasters,
  listObservations,
  listProfiles,
  listRuns,
  newCommandId,
  pendingKey,
  prepare,
  profileTemplate,
  submit,
  type Master,
  type Observation,
  type Profile,
  type QualityAction,
  type RunEntry,
  type Sealed,
} from "../api/qualityClient";

const CRITERIA = ["coherence", "on-screen-text", "audio-presence", "visible-defects"] as const;
type Verdict = "PASS" | "FAIL";

function errorMessage(error: unknown): string | null {
  return error instanceof Error && error.message ? error.message : null;
}

function readPending(key: string): Sealed | null {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as Sealed) : null;
  } catch {
    return null;
  }
}

function writePending(key: string, sealed: Sealed | null): void {
  try {
    if (sealed) window.localStorage.setItem(key, JSON.stringify(sealed));
    else window.localStorage.removeItem(key);
  } catch {
    // Browser storage is a convenience; the sealed request still works for this page session.
  }
}

/**
 * One sealed action: prepare shows the server-built request for confirmation; confirm submits it unchanged and
 * keeps it in browser storage until a result is shown, so a lost response can be resent.
 */
function useSealedAction(projectName: string, action: QualityAction) {
  const key = pendingKey(projectName, action);
  const [prepared, setPrepared] = useState<Sealed | null>(() => readPending(key));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = useRef<AbortController | null>(null);
  useEffect(() => () => current.current?.abort(), []);

  const begin = (): AbortSignal => {
    current.current?.abort();
    current.current = new AbortController();
    setBusy(true);
    setError(null);
    return current.current.signal;
  };
  const end = (signal: AbortSignal) => {
    if (!signal.aborted) setBusy(false);
  };

  const ready = async (intent: Record<string, unknown>, fallback: string) => {
    const signal = begin();
    try {
      const sealed = await prepare(projectName, action, intent, { signal });
      if (!signal.aborted) setPrepared(sealed);
    } catch (failure: unknown) {
      if (!signal.aborted) setError(errorMessage(failure) ?? fallback);
    } finally {
      end(signal);
    }
  };

  const confirm = async (fallback: string): Promise<Record<string, unknown> | null> => {
    if (!prepared) return null;
    writePending(key, prepared);
    const signal = begin();
    try {
      const result = await submit(projectName, action, prepared, { signal });
      if (signal.aborted) return null;
      writePending(key, null);
      setPrepared(null);
      return result;
    } catch (failure: unknown) {
      if (!signal.aborted) setError(errorMessage(failure) ?? fallback);
      return null;
    } finally {
      end(signal);
    }
  };

  const discard = () => {
    writePending(key, null);
    setPrepared(null);
  };

  return { prepared, busy, error, ready, confirm, discard };
}

function Summary({ sealed, labels }: { sealed: Sealed; labels: Record<string, string> }) {
  const request = sealed.request;
  const subject = (request.subject ?? {}) as Record<string, unknown>;
  const command = (request.command ?? {}) as Record<string, unknown>;
  const rows: [string, unknown][] = [
    [labels.command, command.command_id ?? request.command_id ?? request.execution_ref],
    [labels.decision, subject.decision ?? request.status],
    [labels.expires, subject.requested_expires_at],
    [labels.requirement, request.requirement_id],
  ];
  return (
    <dl className="qa-summary font-mono text-[11px]">
      {rows
        .filter(([, value]) => value !== undefined && value !== null && value !== "")
        .map(([label, value]) => (
          <div key={label}>
            <dt className="text-text-3">{label}</dt>
            <dd className="text-text">{String(value)}</dd>
          </div>
        ))}
    </dl>
  );
}

interface QualityPageProps {
  projectName: string;
}

export default function QualityPage({ projectName }: QualityPageProps) {
  const { t } = useTranslation("dashboard");
  const [masters, setMasters] = useState<Master[] | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [root, setRoot] = useState("");
  const [profileKey, setProfileKey] = useState("");
  const [observations, setObservations] = useState<Observation[]>([]);
  const [runs, setRuns] = useState<RunEntry[]>([]);
  const [template, setTemplate] = useState({
    platform_profile_id: "youtube-long",
    width: 1920,
    height: 1080,
    min_duration_ms: 5000,
    max_duration_ms: 900000,
    locales: "en",
  });
  const [policyJson, setPolicyJson] = useState("");
  const [cohort, setCohort] = useState("cohort");
  const [surface, setSurface] = useState("video");
  const [supersession, setSupersession] = useState<"HISTORICAL_ONLY" | "REEVALUATE_CURRENT">("HISTORICAL_ONLY");
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>(() => Object.fromEntries(CRITERIA.map((c) => [c, "PASS"])));
  const [notes, setNotes] = useState("");
  const [decision, setDecision] = useState<"PASS" | "REWORK" | "WAIVE">("PASS");
  const [reason, setReason] = useState("");
  const [ttlHours, setTtlHours] = useState(24);

  const publish = useSealedAction(projectName, "profiles");
  const probe = useSealedAction(projectName, "probes");
  const review = useSealedAction(projectName, "reviews");
  const seal = useSealedAction(projectName, "runs");
  const dispose = useSealedAction(projectName, "dispositions");

  const selected = profiles.find((p) => `${p.profile_id}@${p.revision}` === profileKey) ?? null;

  const reload = useCallback(
    (signal: AbortSignal) =>
      Promise.all([listMasters(projectName, { signal }), listProfiles(projectName, { signal })]).then(
        ([found, published]) => {
          if (signal.aborted) return;
          setMasters(found.masters);
          setProfiles(published.profiles);
          setLoadError(null);
        },
        (failure: unknown) => {
          if (!signal.aborted) setLoadError(errorMessage(failure) ?? t("quality_load_failed"));
        },
      ),
    [projectName, t],
  );

  useEffect(() => {
    const controller = new AbortController();
    void reload(controller.signal);
    return () => controller.abort();
  }, [reload]);

  const refreshSubject = useCallback(
    (signal: AbortSignal) => {
      if (!root || !selected) return Promise.resolve();
      return Promise.all([
        listObservations(projectName, { profile_id: selected.profile_id, revision: selected.revision, root }, { signal }),
        listRuns(projectName, root, { signal }),
      ]).then(
        ([found, sealed]) => {
          if (signal.aborted) return;
          setObservations(found.observations);
          setRuns(sealed.runs);
        },
        (failure: unknown) => {
          if (!signal.aborted) setLoadError(errorMessage(failure) ?? t("quality_load_failed"));
        },
      );
    },
    [projectName, root, selected, t],
  );

  useEffect(() => {
    const controller = new AbortController();
    void refreshSubject(controller.signal);
    return () => controller.abort();
  }, [refreshSubject]);

  const after = async (result: Record<string, unknown> | null) => {
    if (!result) return;
    const controller = new AbortController();
    await reload(controller.signal);
    await refreshSubject(controller.signal);
  };

  const loadTemplate = async () => {
    try {
      const found = await profileTemplate(projectName, template);
      setPolicyJson(JSON.stringify(found.policy, null, 2));
    } catch (failure: unknown) {
      setLoadError(errorMessage(failure) ?? t("quality_load_failed"));
    }
  };

  const scope = selected ? { profile_id: selected.profile_id, revision: selected.revision, root_artifact_key: root } : null;
  const latest = runs[0] ?? null;
  const labels = {
    command: t("quality_summary_command"),
    decision: t("quality_summary_decision"),
    expires: t("quality_summary_expires"),
    requirement: t("quality_summary_requirement"),
  };
  const errors = [publish.error, probe.error, review.error, seal.error, dispose.error, loadError].filter(Boolean);

  const confirmBlock = (action: ReturnType<typeof useSealedAction>, label: string, fallback: string) =>
    action.prepared ? (
      <div className="qa-confirm mt-3" role="group" aria-label={t("quality_confirm_group")}>
        <p className="text-xs text-text-2">{t("quality_confirm_hint")}</p>
        <Summary sealed={action.prepared} labels={labels} />
        <div className="pk-actions">
          <button type="button" className="fm-btn fm-btn-accent" disabled={action.busy} onClick={() => void action.confirm(fallback).then(after)}>
            {label}
          </button>
          <button type="button" className="fm-btn" disabled={action.busy} onClick={action.discard}>
            {t("quality_discard")}
          </button>
        </div>
      </div>
    ) : null;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-bg">
      <header className="fm-header border-b border-hairline py-2.5">
        <p className="font-mono text-[10px] tracking-[0.18em] text-text-3">PROJECT · QUALITY</p>
        <h1 className="font-editorial text-xl leading-tight text-text">{t("quality_title")}</h1>
        <p className="mt-0.5 max-w-2xl text-xs text-text-2">{t("quality_subtitle")}</p>
      </header>

      <div className="mx-auto grid w-full max-w-6xl gap-5 px-4 py-5">
        {errors.length > 0 ? (
          <div role="alert" className="rounded-md border border-hairline-strong p-3 text-sm text-text-2">
            {errors[0]}
          </div>
        ) : null}

        <section aria-labelledby="qa-master" className="pk-card">
          <h2 id="qa-master" className="pk-kicker font-mono">MASTER</h2>
          {masters === null ? <p className="text-sm text-text-3">{t("quality_loading")}</p> : null}
          {masters && masters.length === 0 ? <p className="text-sm text-text-3">{t("quality_no_masters")}</p> : null}
          {masters && masters.length > 0 ? (
            <label className="text-xs text-text-2">
              {t("quality_master")}
              <select className="fm-input" value={root} onChange={(event) => setRoot(event.target.value)}>
                <option value="">{t("quality_choose")}</option>
                {masters.map((master) => (
                  <option key={master.artifact_key} value={master.artifact_key} disabled={!master.resolvable}>
                    {master.artifact_path} · {master.selected_candidate_id}
                    {master.resolvable ? "" : ` — ${t("quality_master_stale")}`}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </section>

        <section aria-labelledby="qa-profile" className="pk-card">
          <h2 id="qa-profile" className="pk-kicker font-mono">PROFILE</h2>
          {profiles.length > 0 ? (
            <label className="text-xs text-text-2">
              {t("quality_profile")}
              <select className="fm-input" value={profileKey} onChange={(event) => setProfileKey(event.target.value)}>
                <option value="">{t("quality_choose")}</option>
                {profiles.map((profile) => (
                  <option key={profile.profile_id} value={`${profile.profile_id}@${profile.revision}`}>
                    {profile.cohort_id} · {profile.product_surface} · r{profile.revision}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <p className="text-sm text-text-3">{t("quality_no_profiles")}</p>
          )}
          <div className="fm-grid mt-3">
            <label className="text-xs text-text-2">
              {t("quality_platform")}
              <input className="fm-input" value={template.platform_profile_id} onChange={(event) => setTemplate({ ...template, platform_profile_id: event.target.value })} />
            </label>
            <label className="text-xs text-text-2">
              {t("quality_width")}
              <input className="fm-input" type="number" value={template.width} onChange={(event) => setTemplate({ ...template, width: Number(event.target.value) })} />
            </label>
            <label className="text-xs text-text-2">
              {t("quality_height")}
              <input className="fm-input" type="number" value={template.height} onChange={(event) => setTemplate({ ...template, height: Number(event.target.value) })} />
            </label>
            <label className="text-xs text-text-2">
              {t("quality_min_duration")}
              <input className="fm-input" type="number" value={template.min_duration_ms} onChange={(event) => setTemplate({ ...template, min_duration_ms: Number(event.target.value) })} />
            </label>
            <label className="text-xs text-text-2">
              {t("quality_max_duration")}
              <input className="fm-input" type="number" value={template.max_duration_ms} onChange={(event) => setTemplate({ ...template, max_duration_ms: Number(event.target.value) })} />
            </label>
            <label className="text-xs text-text-2">
              {t("quality_locales")}
              <input className="fm-input" value={template.locales} onChange={(event) => setTemplate({ ...template, locales: event.target.value })} />
            </label>
          </div>
          <div className="pk-actions">
            <button type="button" className="fm-btn" onClick={() => void loadTemplate()}>
              {t("quality_load_template")}
            </button>
          </div>
          {policyJson ? (
            <div className="fm-grid mt-3">
              <label className="text-xs text-text-2 pk-wide">
                {t("quality_policy")}
                <textarea className="fm-input font-mono" rows={8} value={policyJson} onChange={(event) => setPolicyJson(event.target.value)} />
              </label>
              <label className="text-xs text-text-2">
                {t("quality_cohort")}
                <input className="fm-input" value={cohort} onChange={(event) => setCohort(event.target.value)} />
              </label>
              <label className="text-xs text-text-2">
                {t("quality_surface")}
                <input className="fm-input" value={surface} onChange={(event) => setSurface(event.target.value)} />
              </label>
              <label className="text-xs text-text-2">
                {t("quality_supersession")}
                <select className="fm-input" value={supersession} onChange={(event) => setSupersession(event.target.value as typeof supersession)}>
                  <option value="HISTORICAL_ONLY">{t("quality_supersession_historical")}</option>
                  <option value="REEVALUATE_CURRENT">{t("quality_supersession_reevaluate")}</option>
                </select>
              </label>
            </div>
          ) : null}
          <div className="pk-actions">
            <button
              type="button"
              className="fm-btn fm-btn-accent"
              disabled={!policyJson || publish.busy}
              onClick={() => {
                let policy: Record<string, unknown>;
                try {
                  policy = JSON.parse(policyJson) as Record<string, unknown>;
                } catch {
                  return;
                }
                void publish.ready(
                  {
                    command_id: newCommandId("publish"),
                    profile_id: selected?.profile_id ?? null,
                    expected_profile_revision: selected?.revision ?? 0,
                    cohort_id: selected?.cohort_id ?? cohort,
                    product_surface: selected?.product_surface ?? surface,
                    policy,
                    supersession_effect: supersession,
                  },
                  t("quality_action_failed"),
                );
              }}
            >
              {selected ? t("quality_prepare_revision") : t("quality_prepare_publish")}
            </button>
          </div>
          {confirmBlock(publish, t("quality_publish"), t("quality_action_failed"))}
        </section>

        <section aria-labelledby="qa-probes" className="pk-card">
          <h2 id="qa-probes" className="pk-kicker font-mono">PROBES</h2>
          {!scope ? <p className="text-sm text-text-3">{t("quality_choose_first")}</p> : null}
          <div className="pk-actions">
            {(["technical-container", "technical-decode"] as const).map((requirement) => (
              <button
                key={requirement}
                type="button"
                className="fm-btn"
                disabled={!scope || probe.busy || Boolean(probe.prepared)}
                onClick={() => scope && void probe.ready({ command_id: newCommandId("probe"), ...scope, requirement_id: requirement }, t("quality_action_failed"))}
              >
                {t(requirement === "technical-container" ? "quality_probe_container" : "quality_probe_decode")}
              </button>
            ))}
          </div>
          {confirmBlock(probe, t("quality_run_probe"), t("quality_action_failed"))}
          {observations.length > 0 ? (
            <ul className="pk-entries font-mono text-[11px] text-text-2">
              {observations.map((observation) => (
                <li key={observation.observation_id} data-status={observation.status}>
                  {observation.requirement_id} · {observation.status}
                </li>
              ))}
            </ul>
          ) : null}
        </section>

        <section aria-labelledby="qa-review" className="pk-card">
          <h2 id="qa-review" className="pk-kicker font-mono">REVIEW</h2>
          {CRITERIA.map((criterion) => (
            <fieldset key={criterion} className="pk-group">
              <legend className="text-xs text-text-2">{t(`quality_criterion_${criterion.replaceAll("-", "_")}`)}</legend>
              {(["PASS", "FAIL"] as const).map((value) => (
                <label key={value} className="mr-3 text-xs text-text-2">
                  <input
                    type="radio"
                    name={`qa-${criterion}`}
                    checked={verdicts[criterion] === value}
                    onChange={() => setVerdicts((current) => ({ ...current, [criterion]: value }))}
                  />{" "}
                  {value === "PASS" ? t("quality_verdict_pass") : t("quality_verdict_fail")}
                </label>
              ))}
            </fieldset>
          ))}
          <label className="text-xs text-text-2">
            {t("quality_notes")}
            <textarea className="fm-input" rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} />
          </label>
          <div className="pk-actions">
            <button
              type="button"
              className="fm-btn"
              disabled={!scope || review.busy || Boolean(review.prepared)}
              onClick={() =>
                scope &&
                void review.ready(
                  {
                    command_id: newCommandId("review"),
                    ...scope,
                    status: Object.values(verdicts).every((v) => v === "PASS") ? "PASS" : "FAIL",
                    criteria_verdicts: verdicts,
                    findings: [],
                    notes,
                  },
                  t("quality_action_failed"),
                )
              }
            >
              {t("quality_prepare_review")}
            </button>
          </div>
          {confirmBlock(review, t("quality_record_review"), t("quality_action_failed"))}
        </section>

        <section aria-labelledby="qa-seal" className="pk-card">
          <h2 id="qa-seal" className="pk-kicker font-mono">SEAL</h2>
          <div className="pk-actions">
            <button
              type="button"
              className="fm-btn"
              disabled={!scope || observations.length === 0 || seal.busy || Boolean(seal.prepared)}
              onClick={() =>
                scope &&
                void seal.ready(
                  { command_id: newCommandId("seal"), ...scope, observation_ids: observations.map((o) => o.observation_id) },
                  t("quality_action_failed"),
                )
              }
            >
              {t("quality_prepare_seal")}
            </button>
          </div>
          {confirmBlock(seal, t("quality_seal_run"), t("quality_action_failed"))}
        </section>

        <section aria-labelledby="qa-disposition" className="pk-card">
          <h2 id="qa-disposition" className="pk-kicker font-mono">DISPOSITION</h2>
          {!latest ? <p className="text-sm text-text-3">{t("quality_no_runs")}</p> : null}
          <div className="fm-grid">
            <label className="text-xs text-text-2">
              {t("quality_decision")}
              <select className="fm-input" value={decision} onChange={(event) => setDecision(event.target.value as typeof decision)}>
                <option value="PASS">PASS</option>
                <option value="REWORK">REWORK</option>
                <option value="WAIVE">WAIVE</option>
              </select>
            </label>
            <label className="text-xs text-text-2">
              {t("quality_ttl_hours")}
              <input className="fm-input" type="number" min={1} max={decision === "WAIVE" ? 24 : 168} value={ttlHours} onChange={(event) => setTtlHours(Number(event.target.value))} />
            </label>
            <label className="text-xs text-text-2 pk-wide">
              {t("quality_reason")}
              <input className="fm-input" value={reason} onChange={(event) => setReason(event.target.value)} />
            </label>
          </div>
          <div className="pk-actions">
            <button
              type="button"
              className="fm-btn"
              disabled={!latest || !reason.trim() || dispose.busy || Boolean(dispose.prepared)}
              onClick={() =>
                latest &&
                void dispose.ready(
                  {
                    command_id: newCommandId("dispose"),
                    run_id: latest.run.run_id,
                    decision,
                    reason: reason.trim(),
                    expected_disposition_version: latest.disposition_version,
                    requested_ttl_seconds: ttlHours * 3600,
                  },
                  t("quality_action_failed"),
                )
              }
            >
              {t("quality_prepare_disposition")}
            </button>
          </div>
          {confirmBlock(dispose, t("quality_issue_disposition"), t("quality_action_failed"))}
        </section>

        <section aria-labelledby="qa-runs" className="pk-card">
          <h2 id="qa-runs" className="pk-kicker font-mono">RUNS</h2>
          {runs.length === 0 ? <p className="text-sm text-text-3">{t("quality_no_runs")}</p> : null}
          <ul className="pk-entries text-xs text-text-2">
            {runs.map((entry) => {
              const ready = entry.readiness.state === "READY" && entry.validity.state === "CURRENT";
              const href = `/app/projects/${encodeURIComponent(projectName)}/packaging?${new URLSearchParams({
                run: entry.run.run_id,
                digest: entry.run_digest,
                artifact: root,
                cohort: selected?.cohort_id ?? "",
                surface: selected?.product_surface ?? "",
              }).toString()}`;
              return (
                <li key={entry.run.run_id} data-ready={ready}>
                  <span className="font-mono text-[11px]">{entry.run.run_id.slice(0, 8)}</span>{" "}
                  {t("quality_run_state", { validity: entry.validity.state, readiness: entry.readiness.state })}{" "}
                  {ready ? (
                    <a className="fm-btn inline-block" href={href}>
                      {t("quality_package_run")}
                    </a>
                  ) : (
                    <span className="text-text-3">{t("quality_not_ready")}</span>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      </div>
    </div>
  );
}
