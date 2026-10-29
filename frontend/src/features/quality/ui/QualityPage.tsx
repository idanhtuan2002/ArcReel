/**
 * Quality review of an approved video (route `quality`): pick the master and an exact profile revision, run the two
 * probes, record the Human review, seal a run from chosen observations, issue the decision on a chosen run, then
 * open that run in Packaging. Each action is prepared on the server, shown in full for confirmation and submitted
 * unchanged; nothing here decides whether a video passes.
 */
import "../../formats/ui/formats.css";
import "../../packaging/ui/packaging.css";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";


import {
  commandOf,
  listMasters,
  listObservations,
  listProbes,
  listProfiles,
  listRevisions,
  listRuns,
  newCommandId,
  pendingPrefix,
  prepare,
  profileTemplate,
  readRevision,
  readRun,
  readSession,
  submit,
  type Master,
  type Observation,
  type ProbeAttempt,
  type Profile,
  type QualityAction,
  type RunEntry,
  type Sealed,
} from "../api/qualityClient";

const CRITERIA = ["coherence", "on-screen-text", "audio-presence", "visible-defects"] as const;
const REQUIREMENTS = ["technical-container", "technical-decode", "review"] as const;
type Verdict = "PASS" | "FAIL";
type FindingDraft = { rule_id: string; severity: "BLOCKING" | "ADVISORY"; locator: string };

function errorMessage(error: unknown): string | null {
  return error instanceof Error && error.message ? error.message : null;
}

function storedPending(prefix: string): Sealed[] {
  try {
    const found: Sealed[] = [];
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index);
      if (key?.startsWith(prefix)) found.push(JSON.parse(window.localStorage.getItem(key) ?? "null") as Sealed);
    }
    return found.filter(Boolean);
  } catch {
    return [];
  }
}

function keep(prefix: string, sealed: Sealed, present: boolean): void {
  try {
    const key = prefix + commandOf(sealed);
    if (present) window.localStorage.setItem(key, JSON.stringify(sealed));
    else window.localStorage.removeItem(key);
  } catch {
    // Browser storage is a convenience; the sealed request still works during this page session.
  }
}

/**
 * One sealed action. Prepare shows the server-built request; confirm keeps it in browser storage (per project,
 * actor, action and command), submits it unchanged and forgets it once a result is shown. Unfinished requests from an
 * earlier visit are listed for resend or discard.
 */
function useSealedAction(projectName: string, actor: string, action: QualityAction) {
  const prefix = pendingPrefix(projectName, actor, action);
  const [prepared, setPrepared] = useState<Sealed | null>(null);
  const [pending, setPending] = useState<Sealed[]>(() => storedPending(prefix));
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

  const ready = async (intent: Record<string, unknown>, fallback: string) => {
    const signal = begin();
    try {
      const sealed = await prepare(projectName, action, intent, { signal });
      if (!signal.aborted) setPrepared(sealed);
    } catch (failure: unknown) {
      if (!signal.aborted) setError(errorMessage(failure) ?? fallback);
    } finally {
      if (!signal.aborted) setBusy(false);
    }
  };

  const send = async (sealed: Sealed, fallback: string): Promise<Record<string, unknown> | null> => {
    keep(prefix, sealed, true);
    const signal = begin();
    try {
      const result = await submit(projectName, action, sealed, { signal });
      if (signal.aborted) return null;
      keep(prefix, sealed, false);
      setPrepared(null);
      setPending(storedPending(prefix));
      return result;
    } catch (failure: unknown) {
      if (!signal.aborted) {
        setError(errorMessage(failure) ?? fallback);
        setPending(storedPending(prefix));
      }
      return null;
    } finally {
      if (!signal.aborted) setBusy(false);
    }
  };

  const discard = (sealed: Sealed | null) => {
    if (sealed) keep(prefix, sealed, false);
    setPrepared(null);
    setPending(storedPending(prefix));
  };

  return { prepared, pending, busy, error, ready, send, discard };
}

type SealedAction = ReturnType<typeof useSealedAction>;

/** Every consequential field of a prepared request, read from the sealed request itself. */
function summaryRows(action: QualityAction, request: Record<string, unknown>): [string, string][] {
  const subject = (request.subject ?? {}) as Record<string, unknown>;
  const draft = (subject.profile_draft ?? {}) as Record<string, unknown>;
  const profile = (request.profile ?? {}) as Record<string, unknown>;
  const master = ((request.subject as Record<string, unknown> | undefined)?.master_binding ?? {}) as Record<string, unknown>;
  const root = (master.root ?? {}) as Record<string, unknown>;
  const runSubject = ((subject.subject ?? {}) as Record<string, unknown>).master_binding as Record<string, unknown> | undefined;
  const text = (value: unknown) => (value === undefined || value === null ? "" : typeof value === "string" ? value : JSON.stringify(value));
  switch (action) {
    case "profiles":
      return [
        ["profile", `${text(draft.profile_id)} r${text(draft.revision)}`],
        ["cohort", `${text(draft.cohort_id)} · ${text(draft.product_surface)}`],
        ["supersession", text(draft.supersession_effect)],
        ["policy", text(draft.policy_digest)],
      ];
    case "probes":
      return [
        ["master", text(root.artifact_key)],
        ["candidate", `${text(root.candidate_id)} · ${text(root.content_digest)}`],
        ["profile", `${text(profile.profile_id)} r${text(profile.revision)}`],
        ["requirement", text(request.requirement_id)],
        ["command", text(request.execution_ref)],
      ];
    case "reviews":
      return [
        ["master", text(root.artifact_key)],
        ["candidate", `${text(root.candidate_id)} · ${text(root.content_digest)}`],
        ["profile", `${text(profile.profile_id)} r${text(profile.revision)}`],
        ["status", text(request.status)],
        ["findings", String(((request.findings as unknown[]) ?? []).length)],
        ["evidence", text(request.reviewer_evidence_digest)],
      ];
    case "runs":
      return [
        ["master", text(((runSubject?.root ?? {}) as Record<string, unknown>).artifact_key)],
        ["candidate", text(((runSubject?.root ?? {}) as Record<string, unknown>).content_digest)],
        ["profile", `${text(subject.profile_id)} r${text(subject.profile_revision)}`],
        ["observations", ((subject.observations as { observation_id: string }[]) ?? []).map((o) => o.observation_id).join(", ")],
      ];
    case "dispositions":
      return [
        ["run", text(subject.quality_run_id)],
        ["decision", text(subject.decision)],
        ["reason", text(subject.reason)],
        ["waivers", text(subject.waiver_bindings)],
        ["expires", text(subject.requested_expires_at)],
      ];
  }
}

/** The bulky sealed content a Human confirms: the policy of a publication, the findings of a review. */
function Details({ action, request }: { action: QualityAction; request: Record<string, unknown> }) {
  const { t } = useTranslation("dashboard");
  if (action === "profiles") {
    const draft = ((request.subject ?? {}) as Record<string, unknown>).profile_draft as Record<string, unknown> | undefined;
    return (
      <details className="mt-2 text-xs text-text-2">
        <summary>{t("quality_field_policy_body")}</summary>
        <pre className="qa-pre font-mono text-[11px]">{JSON.stringify(draft?.policy ?? {}, null, 2)}</pre>
      </details>
    );
  }
  if (action === "reviews") {
    const rows = (request.findings as { subject_locator: string; severity: string }[] | undefined) ?? [];
    return rows.length === 0 ? null : (
      <ul className="pk-entries font-mono text-[11px] text-text-2">
        {rows.map((row) => (
          <li key={row.subject_locator + row.severity}>
            {row.subject_locator} · {row.severity}
          </li>
        ))}
      </ul>
    );
  }
  return null;
}

interface ConfirmProps {
  action: QualityAction;
  sealed: SealedAction;
  label: string;
  fallback: string;
  onDone: (result: Record<string, unknown> | null) => void;
}

function Confirm({ action, sealed, label, fallback, onDone }: ConfirmProps) {
  const { t } = useTranslation("dashboard");
  const envelopes = sealed.prepared ? [sealed.prepared] : sealed.pending;
  if (envelopes.length === 0) return null;
  return (
    <>
      {envelopes.map((envelope) => (
        <div key={commandOf(envelope)} className="qa-confirm mt-3" role="group" aria-label={t("quality_confirm_group")}>
          <p className="text-xs text-text-2">{sealed.prepared ? t("quality_confirm_hint") : t("quality_pending_hint")}</p>
          <dl className="qa-summary font-mono text-[11px]">
            {summaryRows(action, envelope.request).map(([name, value]) => (
              <div key={name}>
                <dt className="text-text-3">{t(`quality_field_${name}`)}</dt>
                <dd className="text-text">{value || "—"}</dd>
              </div>
            ))}
          </dl>
          <Details action={action} request={envelope.request} />
          <div className="pk-actions">
            <button type="button" className="fm-btn fm-btn-accent" disabled={sealed.busy} onClick={() => void sealed.send(envelope, fallback).then(onDone)}>
              {sealed.prepared ? label : t("quality_resend")}
            </button>
            <button type="button" className="fm-btn" disabled={sealed.busy} onClick={() => sealed.discard(envelope)}>
              {t("quality_discard")}
            </button>
          </div>
        </div>
      ))}
    </>
  );
}

function Locked({ locked, children }: { locked: boolean; children: ReactNode }) {
  return (
    <fieldset disabled={locked} className="qa-fieldset">
      {children}
    </fieldset>
  );
}

interface QualityPageProps {
  projectName: string;
}

/** The page binds every kept request to the actor the server seals for; a change of actor remounts the workspace. */
export default function QualityPage({ projectName }: QualityPageProps) {
  const { t } = useTranslation("dashboard");
  const [actor, setActor] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    readSession(projectName, { signal: controller.signal }).then(
      (found) => !controller.signal.aborted && setActor(found.actor_id),
      (failure: unknown) => !controller.signal.aborted && setFailed(errorMessage(failure) ?? t("quality_load_failed")),
    );
    return () => controller.abort();
  }, [projectName, t]);
  if (failed)
    return (
      <p role="alert" className="p-4 text-sm text-text-2">
        {failed}
      </p>
    );
  if (!actor) return <p className="p-4 text-sm text-text-3">{t("quality_loading")}</p>;
  return <QualityWorkspace key={actor} projectName={projectName} actor={actor} />;
}

function QualityWorkspace({ projectName, actor }: QualityPageProps & { actor: string }) {
  const { t } = useTranslation("dashboard");
  const [masters, setMasters] = useState<Master[] | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [revisions, setRevisions] = useState<number[]>([]);
  const [selected, setSelected] = useState<Profile | null>(null);
  // What the operator chose; `selected` follows once that exact revision has been read.
  const [choice, setChoice] = useState<{ profileId: string; revision: number | null } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [root, setRoot] = useState("");
  const [observations, setObservations] = useState<Observation[]>([]);
  const [probes, setProbes] = useState<ProbeAttempt[]>([]);
  const [moreProbes, setMoreProbes] = useState<string | null>(null);
  const [moreObservations, setMoreObservations] = useState<string[]>([]);
  const [runs, setRuns] = useState<RunEntry[]>([]);
  const [olderRuns, setOlderRuns] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<(RunEntry & { observations: Observation[] }) | null>(null);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [runId, setRunId] = useState("");
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
  const [findings, setFindings] = useState<FindingDraft[]>([]);
  const [notes, setNotes] = useState("");
  const [decision, setDecision] = useState<"PASS" | "REWORK" | "WAIVE">("PASS");
  const [waived, setWaived] = useState<Record<string, boolean>>({});
  const [reason, setReason] = useState("");
  const [ttlHours, setTtlHours] = useState(24);

  const publish = useSealedAction(projectName, actor, "profiles");
  const probe = useSealedAction(projectName, actor, "probes");
  const review = useSealedAction(projectName, actor, "reviews");
  const seal = useSealedAction(projectName, actor, "runs");
  const dispose = useSealedAction(projectName, actor, "dispositions");

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

  const scopeKey = root && selected ? `${root}|${selected.profile_id}|${selected.revision}` : "";
  const activeScope = useRef(scopeKey);
  useEffect(() => {
    activeScope.current = scopeKey;
  }, [scopeKey]);

  const refreshSubject = useCallback(
    (signal: AbortSignal) => {
      if (!root || !selected) return Promise.resolve();
      const key = `${root}|${selected.profile_id}|${selected.revision}`;
      const live = () => !signal.aborted && activeScope.current === key;
      const scope = { profile_id: selected.profile_id, revision: selected.revision, root };
      // Independent reads: a drifted current subject must not hide the run or probe history.
      const failed = (failure: unknown) => {
        if (live()) setLoadError(errorMessage(failure) ?? t("quality_load_failed"));
      };
      return Promise.all([
        listObservations(projectName, scope, { signal }).then((found) => {
          if (!live()) return;
          setObservations(found.observations);
          setMoreObservations(found.more);
        }, failed),
        listProbes(projectName, scope, null, { signal }).then((found) => {
          if (!live()) return;
          setProbes(found.probes);
          setMoreProbes(found.next_after);
        }, failed),
        listRuns(projectName, root, null, { signal }).then((found) => {
          if (!live()) return;
          setRuns(found.runs);
          setOlderRuns(found.next_before);
        }, failed),
      ]).then(() => undefined);
    },
    [projectName, root, selected, t],
  );

  useEffect(() => {
    const controller = new AbortController();
    void refreshSubject(controller.signal);
    return () => controller.abort();
  }, [refreshSubject]);

  // One controller per data lifetime: the chosen profile revision, and the chosen run's detail.
  const revisionRead = useRef<AbortController | null>(null);
  const runRead = useRef<AbortController | null>(null);
  const currentRun = useRef("");

  const readChosenRun = async (id: string) => {
    runRead.current?.abort();
    const controller = new AbortController();
    runRead.current = controller;
    try {
      const detail = await readRun(projectName, id, { signal: controller.signal });
      if (!controller.signal.aborted && currentRun.current === id) setRunDetail(detail);
    } catch (failure: unknown) {
      if (!controller.signal.aborted) setLoadError(errorMessage(failure) ?? t("quality_load_failed"));
    }
  };

  const clearScope = () => {
    activeScope.current = "";
    setObservations([]);
    setProbes([]);
    setMoreProbes(null);
    setMoreObservations([]);
    setRuns([]);
    setOlderRuns(null);
    setRunDetail(null);
    runRead.current?.abort();
    currentRun.current = "";
    setChosen({});
    setRunId("");
    setWaived({});
  };

  const after = async (result: Record<string, unknown> | null) => {
    if (!result) return;
    const controller = new AbortController();
    await reload(controller.signal);
    await refreshSubject(controller.signal);
    // A decision moves the run's disposition version; the next decision must carry the new one.
    if (currentRun.current) await readChosenRun(currentRun.current);
  };

  const rotateRevisionRead = () => {
    revisionRead.current?.abort();
    const controller = new AbortController();
    revisionRead.current = controller;
    return controller.signal;
  };

  const chooseProfile = async (profileId: string) => {
    const signal = rotateRevisionRead();
    clearScope();
    setSelected(null);
    setRevisions([]);
    setChoice(profileId ? { profileId, revision: null } : null);
    if (!profileId) return;
    try {
      const found = await listRevisions(projectName, profileId, { signal });
      if (signal.aborted) return;
      setRevisions(found.revisions.map((item) => item.revision));
      const latest = found.revisions.at(-1)?.revision;
      if (latest === undefined) return;
      setChoice({ profileId, revision: latest });
      const read = await readRevision(projectName, profileId, latest, { signal });
      if (!signal.aborted) setSelected(read.profile);
    } catch (failure: unknown) {
      if (!signal.aborted) setLoadError(errorMessage(failure) ?? t("quality_load_failed"));
    }
  };

  const chooseRevision = async (revision: number) => {
    if (!choice) return;
    const profileId = choice.profileId;
    setChoice({ profileId, revision });
    const signal = rotateRevisionRead();
    clearScope();
    setSelected(null);
    try {
      const read = await readRevision(projectName, profileId, revision, { signal });
      if (!signal.aborted) setSelected(read.profile);
    } catch (failure: unknown) {
      if (!signal.aborted) setLoadError(errorMessage(failure) ?? t("quality_load_failed"));
    }
  };

  const chooseRun = async (id: string) => {
    currentRun.current = id;
    setRunId(id);
    setRunDetail(null);
    setWaived({});
    await readChosenRun(id);
  };

  const loadMoreProbes = async () => {
    if (!moreProbes || !selected) return;
    const key = activeScope.current;
    try {
      const found = await listProbes(projectName, { profile_id: selected.profile_id, revision: selected.revision, root }, moreProbes);
      if (activeScope.current !== key) return;
      setProbes((current) => [...current, ...found.probes]);
      setMoreProbes(found.next_after);
    } catch (failure: unknown) {
      setLoadError(errorMessage(failure) ?? t("quality_load_failed"));
    }
  };

  const loadOlderRuns = async () => {
    if (!olderRuns) return;
    const key = activeScope.current;
    try {
      const found = await listRuns(projectName, root, olderRuns);
      if (activeScope.current !== key) return;
      setRuns((current) => [...current, ...found.runs]);
      setOlderRuns(found.next_before);
    } catch (failure: unknown) {
      setLoadError(errorMessage(failure) ?? t("quality_load_failed"));
    }
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
  const ready = Boolean(root && scope);
  const run = runDetail && runDetail.run.run_id === runId ? runDetail : null;
  // Waivable candidates come from the chosen run's own closure: BLOCKING findings of a failed Human slot.
  const reviewFindings = (runDetail?.observations ?? [])
    .filter((o) => o.requirement_id === "review" && o.status === "FAIL")
    .flatMap((o) => o.findings.filter((f) => f.severity === "BLOCKING").map((f) => ({ ...f, observation: o })));
  const errors = [publish.error, probe.error, review.error, seal.error, dispose.error, loadError].filter(Boolean);
  const fallback = t("quality_action_failed");

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
              <select
                className="fm-input"
                value={root}
                onChange={(event) => {
                  clearScope();
                  setRoot(event.target.value);
                }}
              >
                <option value="">{t("quality_choose")}</option>
                {masters.map((master) => (
                  <option key={master.artifact_key} value={master.artifact_key} disabled={!master.resolvable}>
                    {master.selected_candidate_id} · {master.approval_record}
                    {master.resolvable ? "" : ` — ${t("quality_master_stale")}`}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </section>

        <section aria-labelledby="qa-profile" className="pk-card">
          <h2 id="qa-profile" className="pk-kicker font-mono">PROFILE</h2>
          <Locked locked={Boolean(publish.prepared)}>
            {profiles.length > 0 ? (
              <div className="fm-grid">
                <label className="text-xs text-text-2">
                  {t("quality_profile")}
                  <select className="fm-input" value={choice?.profileId ?? ""} onChange={(event) => void chooseProfile(event.target.value)}>
                    <option value="">{t("quality_choose")}</option>
                    {profiles.map((profile) => (
                      <option key={profile.profile_id} value={profile.profile_id}>
                        {profile.cohort_id} · {profile.product_surface}
                      </option>
                    ))}
                  </select>
                </label>
                {choice?.revision != null ? (
                  <label className="text-xs text-text-2">
                    {t("quality_revision")}
                    <select className="fm-input" value={choice.revision} onChange={(event) => void chooseRevision(Number(event.target.value))}>
                      {revisions.map((revision) => (
                        <option key={revision} value={revision}>
                          r{revision}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
              </div>
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
                  <input className="fm-input" value={selected?.cohort_id ?? cohort} disabled={Boolean(selected)} onChange={(event) => setCohort(event.target.value)} />
                </label>
                <label className="text-xs text-text-2">
                  {t("quality_surface")}
                  <input className="fm-input" value={selected?.product_surface ?? surface} disabled={Boolean(selected)} onChange={(event) => setSurface(event.target.value)} />
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
                      expected_profile_revision: selected ? Math.max(...revisions) : 0,
                      cohort_id: selected?.cohort_id ?? cohort,
                      product_surface: selected?.product_surface ?? surface,
                      policy,
                      supersession_effect: supersession,
                    },
                    fallback,
                  );
                }}
              >
                {selected ? t("quality_prepare_revision") : t("quality_prepare_publish")}
              </button>
            </div>
          </Locked>
          <Confirm
            action="profiles"
            sealed={publish}
            label={t("quality_publish")}
            fallback={fallback}
            onDone={(result) => {
              void after(result);
              const published = (result?.profile ?? null) as Profile | null;
              if (published) void chooseProfile(published.profile_id);
            }}
          />
        </section>

        <section aria-labelledby="qa-probes" className="pk-card">
          <h2 id="qa-probes" className="pk-kicker font-mono">PROBES</h2>
          {!ready ? <p className="text-sm text-text-3">{t("quality_choose_first")}</p> : null}
          <div className="pk-actions">
            {(["technical-container", "technical-decode"] as const).map((requirement) => (
              <button
                key={requirement}
                type="button"
                className="fm-btn"
                disabled={!ready || probe.busy || Boolean(probe.prepared)}
                onClick={() => scope && void probe.ready({ command_id: newCommandId("probe"), ...scope, requirement_id: requirement }, fallback)}
              >
                {t(requirement === "technical-container" ? "quality_probe_container" : "quality_probe_decode")}
              </button>
            ))}
          </div>
          <Confirm action="probes" sealed={probe} label={t("quality_run_probe")} fallback={fallback} onDone={(r) => void after(r)} />
          {probes.length > 0 ? (
            <ul className="pk-entries font-mono text-[11px] text-text-2">
              {probes.map((attempt) => {
                const kept = probe.pending.find((envelope) => envelope.request.execution_ref === attempt.execution_ref);
                const unfinished = attempt.attempt_state === "PLANNED" || attempt.attempt_state === "SUBMITTING" || attempt.attempt_state === "ACCEPTED";
                return (
                  <li key={attempt.execution_ref} data-state={attempt.attempt_state ?? "UNKNOWN"}>
                    {attempt.requirement_id} · {attempt.execution_ref} · {attempt.actor_id} · {attempt.attempt_state ?? "—"} ·{" "}
                    {attempt.status ?? t("quality_probe_no_result")}
                    {attempt.failure ? ` · ${t("quality_probe_failed", { code: attempt.failure.error_code })}` : ""}
                    <span className="block text-text-3">
                      {t("quality_probe_identity", { execution: attempt.execution_id, binding: attempt.master_binding_digest })}
                    </span>
                    {attempt.failure?.resources ? (
                      <details className="text-text-3">
                        <summary>{t("quality_probe_resources")}</summary>
                        <pre className="qa-pre">{JSON.stringify(attempt.failure.resources, null, 2)}</pre>
                      </details>
                    ) : null}
                    {attempt.attempt_state === "SUBMIT_OUTCOME_UNKNOWN" || attempt.attempt_state === "NEEDS_OPERATOR"
                      ? ` · ${t("quality_probe_needs_review")}`
                      : ""}
                    {unfinished && kept ? (
                      <button type="button" className="fm-btn ml-2" disabled={probe.busy} onClick={() => void probe.send(kept, fallback).then(after)}>
                        {t("quality_probe_finish")}
                      </button>
                    ) : null}
                    {unfinished && !kept ? ` · ${t("quality_probe_envelope_lost")}` : ""}
                  </li>
                );
              })}
            </ul>
          ) : null}
          {moreProbes ? (
            <div className="pk-actions">
              <button type="button" className="fm-btn" onClick={() => void loadMoreProbes()}>
                {t("quality_more_probes")}
              </button>
            </div>
          ) : null}
        </section>

        <section aria-labelledby="qa-review" className="pk-card">
          <h2 id="qa-review" className="pk-kicker font-mono">REVIEW</h2>
          <Locked locked={Boolean(review.prepared) || !ready}>
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
            {findings.map((finding, index) => (
              <div key={index} className="fm-grid mt-2" role="group" aria-label={t("quality_finding", { index: index + 1 })}>
                <label className="text-xs text-text-2">
                  {t("quality_finding_criterion")}
                  <select className="fm-input" value={finding.rule_id} onChange={(event) => setFindings((rows) => rows.map((row, i) => (i === index ? { ...row, rule_id: event.target.value } : row)))}>
                    {CRITERIA.map((criterion) => (
                      <option key={criterion} value={criterion}>
                        {t(`quality_criterion_${criterion.replaceAll("-", "_")}`)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-text-2">
                  {t("quality_finding_severity")}
                  <select className="fm-input" value={finding.severity} onChange={(event) => setFindings((rows) => rows.map((row, i) => (i === index ? { ...row, severity: event.target.value as FindingDraft["severity"] } : row)))}>
                    <option value="BLOCKING">{t("packaging_blocking")}</option>
                    <option value="ADVISORY">{t("packaging_advisory")}</option>
                  </select>
                </label>
                <label className="text-xs text-text-2">
                  {t("quality_finding_locator")}
                  <input className="fm-input" value={finding.locator} onChange={(event) => setFindings((rows) => rows.map((row, i) => (i === index ? { ...row, locator: event.target.value } : row)))} />
                </label>
                <button type="button" className="fm-btn" onClick={() => setFindings((rows) => rows.filter((_, i) => i !== index))}>
                  {t("quality_finding_remove")}
                </button>
              </div>
            ))}
            <div className="pk-actions">
              <button type="button" className="fm-btn" disabled={findings.length >= 32} onClick={() => setFindings((rows) => [...rows, { rule_id: "visible-defects", severity: "BLOCKING", locator: "whole" }])}>
                {t("quality_finding_add")}
              </button>
            </div>
            <label className="text-xs text-text-2">
              {t("quality_notes")}
              <textarea className="fm-input" rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} />
            </label>
            <div className="pk-actions">
              <button
                type="button"
                className="fm-btn"
                disabled={!ready || review.busy}
                onClick={() =>
                  scope &&
                  void review.ready(
                    {
                      command_id: newCommandId("review"),
                      ...scope,
                      status: Object.values(verdicts).every((v) => v === "PASS") ? "PASS" : "FAIL",
                      criteria_verdicts: verdicts,
                      findings,
                      notes,
                    },
                    fallback,
                  )
                }
              >
                {t("quality_prepare_review")}
              </button>
            </div>
          </Locked>
          <Confirm action="reviews" sealed={review} label={t("quality_record_review")} fallback={fallback} onDone={(r) => void after(r)} />
        </section>

        <section aria-labelledby="qa-seal" className="pk-card">
          <h2 id="qa-seal" className="pk-kicker font-mono">SEAL</h2>
          <Locked locked={Boolean(seal.prepared)}>
            {REQUIREMENTS.map((requirement) => {
              const options = observations.filter((o) => o.requirement_id === requirement);
              return (
                <fieldset key={requirement} className="pk-group">
                  <legend className="text-xs text-text-2">{t("quality_choose_observation", { requirement })}</legend>
                  {options.length === 0 ? <span className="text-xs text-text-3">{t("quality_no_observation")}</span> : null}
                  {moreObservations.includes(requirement) ? (
                    <span className="block text-xs text-text-3">{t("quality_older_observations_hidden")}</span>
                  ) : null}
                  {options.map((option) => (
                    <label key={option.observation_id} className="mr-3 text-xs text-text-2">
                      <input
                        type="radio"
                        name={`qa-seal-${requirement}`}
                        checked={chosen[requirement] === option.observation_id}
                        onChange={() => setChosen((current) => ({ ...current, [requirement]: option.observation_id }))}
                      />{" "}
                      {option.status} · {new Date(option.observed_at).toLocaleString()}
                    </label>
                  ))}
                </fieldset>
              );
            })}
            <div className="pk-actions">
              <button
                type="button"
                className="fm-btn"
                disabled={!ready || REQUIREMENTS.some((r) => !chosen[r]) || seal.busy}
                onClick={() =>
                  scope &&
                  void seal.ready({ command_id: newCommandId("seal"), ...scope, observation_ids: REQUIREMENTS.map((r) => chosen[r]) }, fallback)
                }
              >
                {t("quality_prepare_seal")}
              </button>
            </div>
          </Locked>
          <Confirm action="runs" sealed={seal} label={t("quality_seal_run")} fallback={fallback} onDone={(r) => void after(r)} />
        </section>

        <section aria-labelledby="qa-runs" className="pk-card">
          <h2 id="qa-runs" className="pk-kicker font-mono">RUNS</h2>
          {runs.length === 0 ? <p className="text-sm text-text-3">{t("quality_no_runs")}</p> : null}
          <ul className="pk-entries text-xs text-text-2">
            {runs.map((entry) => {
              const current = entry.readiness.state === "READY" && entry.validity.state === "CURRENT";
              const href = `/app/projects/${encodeURIComponent(projectName)}/packaging?${new URLSearchParams({
                run: entry.run.run_id,
                digest: entry.run_digest,
                artifact: root,
                cohort: entry.cohort_id ?? "",
                surface: entry.product_surface ?? "",
              }).toString()}`;
              return (
                <li key={entry.run.run_id} data-ready={current}>
                  <label className="mr-2">
                    <input type="radio" name="qa-run" checked={runId === entry.run.run_id} onChange={() => void chooseRun(entry.run.run_id)} />{" "}
                    <span className="font-mono text-[11px]">{entry.run.run_id.slice(0, 8)}</span>
                  </label>
                  {t("quality_run_state", { validity: entry.validity.state, readiness: entry.readiness.state })}{" "}
                  {current ? (
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
          {olderRuns ? (
            <div className="pk-actions">
              <button type="button" className="fm-btn" onClick={() => void loadOlderRuns()}>
                {t("quality_older_runs")}
              </button>
            </div>
          ) : null}
        </section>

        <section aria-labelledby="qa-disposition" className="pk-card">
          <h2 id="qa-disposition" className="pk-kicker font-mono">DISPOSITION</h2>
          {!run ? <p className="text-sm text-text-3">{t("quality_choose_run")}</p> : null}
          <Locked locked={Boolean(dispose.prepared) || !run}>
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
            {decision === "WAIVE" ? (
              <fieldset className="pk-group">
                <legend className="text-xs text-text-2">{t("quality_waive_findings")}</legend>
                {reviewFindings.length === 0 ? <span className="text-xs text-text-3">{t("quality_no_findings")}</span> : null}
                {reviewFindings.map((finding) => (
                  <label key={finding.finding_id} className="mr-3 text-xs text-text-2">
                    <input type="checkbox" checked={Boolean(waived[finding.finding_id])} onChange={(event) => setWaived((current) => ({ ...current, [finding.finding_id]: event.target.checked }))} />{" "}
                    {finding.subject_locator} · {finding.severity}
                  </label>
                ))}
              </fieldset>
            ) : null}
            <div className="pk-actions">
              <button
                type="button"
                className="fm-btn"
                disabled={!run || !reason.trim() || dispose.busy}
                onClick={() =>
                  run &&
                  void dispose.ready(
                    {
                      command_id: newCommandId("dispose"),
                      run_id: run.run.run_id,
                      decision,
                      reason: reason.trim(),
                      waiver_bindings:
                        decision === "WAIVE"
                          ? reviewFindings
                              .filter((finding) => waived[finding.finding_id])
                              .map((finding) => ({
                                rule_id: finding.rule_id,
                                finding_id: finding.finding_id,
                                scope: `${finding.observation.requirement_id}:${finding.observation.slot_id}`,
                                justification: reason.trim(),
                              }))
                          : [],
                      expected_disposition_version: run.disposition_version,
                      requested_ttl_seconds: ttlHours * 3600,
                    },
                    fallback,
                  )
                }
              >
                {t("quality_prepare_disposition")}
              </button>
            </div>
          </Locked>
          <Confirm action="dispositions" sealed={dispose} label={t("quality_issue_disposition")} fallback={fallback} onDone={(r) => void after(r)} />
        </section>
      </div>
    </div>
  );
}
