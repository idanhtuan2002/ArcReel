/**
 * Packaging of an approved video (route `packaging`): save a package revision, run the package check, preview
 * one choice per alternative group with any allowed waivers, select it as the showrunner, then export and
 * download the archive. Every verdict, binding and refusal comes from the server; nothing here decides whether a
 * package is acceptable. The slot's selection, exportability and archives are read back from the server after
 * every selection or export attempt.
 */
import "../../formats/ui/formats.css";
import "./packaging.css";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  appendRevision,
  checkPackage,
  downloadUrl,
  exportPackage,
  getSlotStatus,
  newCommandId,
  previewPackage,
  selectPackage,
  type CandidateRevision,
  type ExportReceipt,
  type PackagingDraft,
  type PackagingObservation,
  type Preview,
  type Slot,
  type SlotStatus,
} from "../api/packagingClient";

const ZERO_DIGEST = `sha256:${"0".repeat(64)}`;

function errorMessage(error: unknown): string | null {
  return error instanceof Error && error.message ? error.message : null;
}

/** One abortable step at a time with busy and error state that never outlive the component. */
function useStep() {
  const current = useRef<AbortController | null>(null);
  useEffect(() => () => current.current?.abort(), []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async <T,>(step: (signal: AbortSignal) => Promise<T>, fallback: string): Promise<T | null> => {
    current.current?.abort();
    const controller = new AbortController();
    current.current = controller;
    setBusy(true);
    setError(null);
    try {
      const result = await step(controller.signal);
      return controller.signal.aborted ? null : result;
    } catch (failure: unknown) {
      if (!controller.signal.aborted) setError(errorMessage(failure) ?? fallback);
      return null;
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }, []);
  return { busy, error, run, fail: setError };
}

interface SlotScope {
  key: string;
  projectName: string;
  slot: Slot;
}

/**
 * The server's view of the slot being edited. Reads always target the current scope, so a refresh requested by an
 * action that finished after the slot changed reads the new slot instead of cancelling it. A scope change or an
 * explicit refresh drops the previous answer, so nothing is shown as current while its reread is pending.
 */
function useSlotStatus(projectName: string, artifact: string, cohort: string, surface: string) {
  const scope = useMemo<SlotScope | null>(
    () =>
      artifact && cohort && surface
        ? {
            key: JSON.stringify([projectName, artifact, cohort, surface]),
            projectName,
            slot: { source_artifact_key: artifact, cohort_id: cohort, product_surface: surface },
          }
        : null,
    [projectName, artifact, cohort, surface],
  );
  const scopeRef = useRef<SlotScope | null>(null);
  const current = useRef<AbortController | null>(null);
  useEffect(() => () => current.current?.abort(), []);
  const [result, setResult] = useState<{ key: string; status: SlotStatus | null } | null>(null);
  const read = useCallback((): Promise<void> => {
    current.current?.abort();
    const target = scopeRef.current;
    if (target === null) return Promise.resolve();
    const controller = new AbortController();
    current.current = controller;
    const settle = (status: SlotStatus | null) => {
      if (!controller.signal.aborted && scopeRef.current?.key === target.key) setResult({ key: target.key, status });
    };
    return getSlotStatus(target.projectName, target.slot, { signal: controller.signal }).then(settle, () => settle(null));
  }, []);
  useEffect(() => {
    scopeRef.current = scope;
    void read();
    return () => setResult(null);
  }, [scope, read]);
  const refresh = useCallback((): Promise<void> => {
    setResult(null);
    return read();
  }, [read]);
  const settled = scope !== null && result?.key === scope.key ? result : null;
  const state: "idle" | "loading" | "failed" = scope === null ? "idle" : !settled ? "loading" : settled.status ? "idle" : "failed";
  return { status: settled?.status ?? null, state, refresh, scoped: scope !== null };
}

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

class DraftFieldError extends Error {}

function parseList<T>(text: string, field: string, message: (field: string) => string): T[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new DraftFieldError(message(field));
  }
  if (!Array.isArray(parsed)) throw new DraftFieldError(message(field));
  return parsed as T[];
}

type StepState = "todo" | "done" | "blocked";

interface PackagingPageProps {
  projectName: string;
}

export default function PackagingPage({ projectName }: PackagingPageProps) {
  const { t } = useTranslation("dashboard");
  const step = useStep();
  const [runId, setRunId] = useState("");
  const [runDigest, setRunDigest] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [hashtags, setHashtags] = useState("");
  const [chaptersJson, setChaptersJson] = useState("[]");
  const [localizationsJson, setLocalizationsJson] = useState("[]");
  const [groupsJson, setGroupsJson] = useState("[]");
  const [assetsJson, setAssetsJson] = useState("[]");
  const [audience, setAudience] = useState("general");
  const [ageRestriction, setAgeRestriction] = useState("");
  const [classificationDigest, setClassificationDigest] = useState(ZERO_DIGEST);
  const [syntheticMedia, setSyntheticMedia] = useState(true);
  const [paidPromotion, setPaidPromotion] = useState(false);
  const [disclosureDigest, setDisclosureDigest] = useState(ZERO_DIGEST);
  const [slot, setSlot] = useState<Slot>({ source_artifact_key: "", cohort_id: "", product_surface: "" });
  const [revision, setRevision] = useState<CandidateRevision | null>(null);
  const [savedDraft, setSavedDraft] = useState<string | null>(null);
  const [headVersion, setHeadVersion] = useState<number | null>(null);
  const [observation, setObservation] = useState<PackagingObservation | null>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<{ inputs: string; value: Preview } | null>(null);
  const [mySelectionId, setMySelectionId] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<ExportReceipt | null>(null);
  const slotStatus = useSlotStatus(projectName, slot.source_artifact_key, slot.cohort_id, slot.product_surface);
  const server = slotStatus.status;

  const draftInputs = JSON.stringify([
    runId,
    title,
    description,
    tags,
    hashtags,
    chaptersJson,
    localizationsJson,
    groupsJson,
    assetsJson,
    audience,
    ageRestriction,
    classificationDigest,
    syntheticMedia,
    paidPromotion,
    disclosureDigest,
  ]);
  const draftUnsaved = revision !== null && savedDraft !== draftInputs;
  const blocking = observation?.findings.filter((finding) => finding.severity === "BLOCKING") ?? [];
  const waivers = blocking
    .filter((finding) => (reasons[finding.finding_id] ?? "").trim())
    .map((finding) => ({ rule_id: finding.rule_id, finding_id: finding.finding_id, reason: reasons[finding.finding_id].trim() }));
  const previewInputs = JSON.stringify([slot, revision?.payload_digest, observation?.observation_id, choices, waivers]);
  // A preview stands only for the exact inputs it was made from; any later edit makes it unselectable.
  const currentPreview = preview && preview.inputs === previewInputs && !draftUnsaved ? preview.value : null;

  const saveRevision = async () => {
    const invalid = (field: string) => t("packaging_json_invalid", { field });
    let draft: PackagingDraft;
    try {
      draft = {
        title,
        description,
        tags: splitList(tags),
        hashtags: splitList(hashtags),
        chapters: parseList(chaptersJson, t("packaging_field_chapters"), invalid),
        localization_variants: parseList(localizationsJson, t("packaging_field_localizations"), invalid),
        audience_classification: {
          audience_category: audience.trim(),
          age_restriction: ageRestriction.trim() || null,
          classification_policy_digest: classificationDigest.trim(),
        },
        disclosure: {
          synthetic_media: syntheticMedia,
          paid_promotion: paidPromotion,
          disclosure_policy_digest: disclosureDigest.trim(),
        },
        variant_groups: parseList(groupsJson, t("packaging_field_variant_groups"), invalid),
        assets: parseList(assetsJson, t("packaging_field_assets"), invalid),
      };
    } catch (failure: unknown) {
      if (failure instanceof DraftFieldError) return void step.fail(failure.message);
      throw failure;
    }
    const inputs = draftInputs;
    const saved = await step.run(
      (signal) =>
        appendRevision(
          projectName,
          {
            command_id: newCommandId("revision"),
            quality_run_id: runId,
            candidate_id: revision?.candidate_id ?? null,
            expected_head_version: headVersion,
            draft,
          },
          { signal },
        ),
      t("packaging_save_failed"),
    );
    if (saved) {
      setRevision(saved.revision);
      setSavedDraft(inputs);
      setHeadVersion(saved.head.head_version);
      setObservation(null);
      setChoices({});
      setReasons({});
      setPreview(null);
    }
  };

  const runCheck = async () => {
    if (!revision) return;
    const checked = await step.run(
      (signal) =>
        checkPackage(
          projectName,
          {
            command_id: newCommandId("check"),
            candidate_id: revision.candidate_id,
            candidate_revision: revision.revision,
            candidate_payload_digest: revision.payload_digest,
            quality_run_id: runId,
            quality_run_digest: runDigest,
          },
          { signal },
        ),
      t("packaging_check_failed"),
    );
    if (checked) {
      setObservation(checked);
      setPreview(null);
    }
  };

  const makePreview = async () => {
    if (!revision || !observation) return;
    const inputs = previewInputs;
    const shown = await step.run(
      (signal) =>
        previewPackage(
          projectName,
          {
            command_id: newCommandId("preview"),
            ...slot,
            candidate_id: revision.candidate_id,
            candidate_revision: revision.revision,
            candidate_payload_digest: revision.payload_digest,
            packaging_observation_id: observation.observation_id,
            selected_variant_ids: Object.values(choices),
            waivers,
          },
          { signal },
        ),
      t("packaging_preview_failed"),
    );
    if (shown) setPreview({ inputs, value: shown });
  };

  const select = async () => {
    if (!currentPreview) return;
    const chosen = await step.run(
      (signal) =>
        selectPackage(
          projectName,
          {
            command_id: newCommandId("select"),
            preview_id: currentPreview.preview.preview_id,
            preview_digest: currentPreview.preview_digest,
            expected_head_version: currentPreview.preview.expected_head_version,
          },
          { signal },
        ),
      t("packaging_select_failed"),
    );
    if (chosen) {
      setMySelectionId(chosen.selection_id);
      setPreview(null);
    }
    await slotStatus.refresh();
  };

  const exportSelected = async () => {
    const selected = server?.selection;
    if (!selected) return;
    const exported = await step.run(
      (signal) =>
        exportPackage(
          projectName,
          { command_id: newCommandId("export"), ...slot, selection_id: selected.selection_id, selection_digest: selected.selection_digest },
          { signal },
        ),
      t("packaging_export_failed"),
    );
    setReceipt(exported);
    await slotStatus.refresh();
  };

  const checkState: StepState = observation
    ? observation.status === "PASS" || blocking.length === 0
      ? "done"
      : "blocked"
    : "todo";
  const ladder: { key: string; label: string; state: StepState }[] = [
    { key: "draft", label: t("packaging_step_draft"), state: revision && !draftUnsaved ? "done" : "todo" },
    { key: "check", label: t("packaging_step_check"), state: checkState },
    { key: "select", label: t("packaging_step_select"), state: server?.selection ? "done" : "todo" },
    {
      key: "export",
      label: t("packaging_step_export"),
      state: server?.exportable && server.exports.some((item) => item.current) ? "done" : "todo",
    },
  ];
  const currentRung = ladder.findIndex((item) => item.state === "todo");
  const groups = revision?.payload.variant_groups ?? [];
  const superseded = mySelectionId !== null && server !== null && server.selection?.selection_id !== mySelectionId;
  const lockedByDraft = step.busy || draftUnsaved;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-bg">
      <header className="fm-header border-b border-hairline py-2.5">
        <p className="font-mono text-[10px] tracking-[0.18em] text-text-3">PROJECT · PACKAGING</p>
        <h1 className="font-editorial text-xl leading-tight text-text">{t("packaging_title")}</h1>
        <p className="mt-0.5 max-w-2xl text-xs text-text-2">{t("packaging_subtitle")}</p>
      </header>

      <ol className="pk-ladder mx-auto w-full max-w-6xl px-4 pt-5" aria-label={t("packaging_progress")}>
        {ladder.map((item, index) => (
          <li key={item.key} className="pk-rung" data-state={item.state} aria-current={index === currentRung ? "step" : undefined}>
            <span className="pk-rung-index font-mono">{index + 1}</span>
            <span className="pk-rung-label">{item.label}</span>
            <span className="sr-only">{t(`packaging_state_${item.state}`)}</span>
          </li>
        ))}
      </ol>

      <div className="mx-auto grid w-full max-w-6xl gap-5 px-4 py-5">
        {step.error ? (
          <div role="alert" className="rounded-md border border-hairline-strong p-3 text-sm text-text-2">
            {step.error}
          </div>
        ) : null}

        <section aria-labelledby="pk-draft" className="pk-card">
          <h2 id="pk-draft" className="pk-kicker font-mono">PACKAGE</h2>
          <div className="fm-grid">
            <label className="text-xs text-text-2">
              {t("packaging_run_id")}
              <input className="fm-input" value={runId} onChange={(event) => setRunId(event.target.value)} />
            </label>
            <label className="text-xs text-text-2">
              {t("packaging_run_digest")}
              <input className="fm-input" value={runDigest} onChange={(event) => setRunDigest(event.target.value)} />
            </label>
            <label className="text-xs text-text-2">
              {t("packaging_field_title")}
              <input className="fm-input" value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label className="text-xs text-text-2">
              {t("packaging_field_tags")}
              <input className="fm-input" value={tags} onChange={(event) => setTags(event.target.value)} />
            </label>
            <label className="text-xs text-text-2 pk-wide">
              {t("packaging_field_description")}
              <textarea className="fm-input" rows={3} value={description} onChange={(event) => setDescription(event.target.value)} />
            </label>
            <label className="text-xs text-text-2">
              {t("packaging_field_hashtags")}
              <input className="fm-input" value={hashtags} onChange={(event) => setHashtags(event.target.value)} />
            </label>
            <label className="text-xs text-text-2">
              {t("packaging_field_chapters")}
              <textarea className="fm-input font-mono" rows={3} value={chaptersJson} onChange={(event) => setChaptersJson(event.target.value)} />
            </label>
            <label className="text-xs text-text-2">
              {t("packaging_field_variant_groups")}
              <textarea className="fm-input font-mono" rows={3} value={groupsJson} onChange={(event) => setGroupsJson(event.target.value)} />
            </label>
            <label className="text-xs text-text-2">
              {t("packaging_field_localizations")}
              <textarea
                className="fm-input font-mono"
                rows={3}
                value={localizationsJson}
                onChange={(event) => setLocalizationsJson(event.target.value)}
              />
            </label>
            <label className="text-xs text-text-2 pk-wide">
              {t("packaging_field_assets")}
              <textarea className="fm-input font-mono" rows={3} value={assetsJson} onChange={(event) => setAssetsJson(event.target.value)} />
            </label>
            <label className="text-xs text-text-2">
              {t("packaging_field_audience")}
              <input className="fm-input" value={audience} onChange={(event) => setAudience(event.target.value)} />
            </label>
            <label className="text-xs text-text-2">
              {t("packaging_field_age_restriction")}
              <input className="fm-input" value={ageRestriction} onChange={(event) => setAgeRestriction(event.target.value)} />
            </label>
            <label className="text-xs text-text-2">
              {t("packaging_field_classification_digest")}
              <input
                className="fm-input font-mono"
                value={classificationDigest}
                onChange={(event) => setClassificationDigest(event.target.value)}
              />
            </label>
            <label className="text-xs text-text-2">
              {t("packaging_field_disclosure_digest")}
              <input className="fm-input font-mono" value={disclosureDigest} onChange={(event) => setDisclosureDigest(event.target.value)} />
            </label>
            <label className="text-xs text-text-2">
              <input type="checkbox" checked={syntheticMedia} onChange={(event) => setSyntheticMedia(event.target.checked)} />{" "}
              {t("packaging_field_synthetic")}
            </label>
            <label className="text-xs text-text-2">
              <input type="checkbox" checked={paidPromotion} onChange={(event) => setPaidPromotion(event.target.checked)} />{" "}
              {t("packaging_field_paid")}
            </label>
          </div>
          <div className="pk-actions">
            <button type="button" className="fm-btn fm-btn-accent" disabled={step.busy || !runId || !title} onClick={() => void saveRevision()}>
              {revision ? t("packaging_save_new_revision") : t("packaging_save_revision")}
            </button>
            {revision ? (
              <p className="text-xs text-text-3" role="status">
                {draftUnsaved ? t("packaging_draft_unsaved") : t("packaging_revision_saved", { revision: revision.revision })}
              </p>
            ) : null}
          </div>
        </section>

        <section aria-labelledby="pk-check" className="pk-card">
          <h2 id="pk-check" className="pk-kicker font-mono">CHECK</h2>
          {!revision ? <p className="text-sm text-text-3">{t("packaging_check_empty")}</p> : null}
          <button type="button" className="fm-btn" disabled={lockedByDraft || !revision || !runDigest} onClick={() => void runCheck()}>
            {t("packaging_run_check")}
          </button>
          {observation ? (
            <div className="mt-3">
              <p className="text-sm" data-verdict={observation.status}>
                {observation.status === "PASS" ? t("packaging_check_pass") : t("packaging_check_fail")}
              </p>
              {observation.findings.length === 0 ? null : (
                <ul className="pk-findings">
                  {observation.findings.map((finding) => (
                    <li key={finding.finding_id} data-severity={finding.severity}>
                      <span className="font-mono text-[11px]">{finding.rule_id}</span>
                      <span className="text-xs text-text-2">{finding.subject_locator}</span>
                      <span className="text-[11px] text-text-3">
                        {finding.severity === "BLOCKING" ? t("packaging_blocking") : t("packaging_advisory")}
                      </span>
                      {finding.severity === "BLOCKING" ? (
                        <label className="text-xs text-text-2">
                          {t("packaging_waiver_reason")}
                          <input
                            className="fm-input"
                            value={reasons[finding.finding_id] ?? ""}
                            onChange={(event) => setReasons((current) => ({ ...current, [finding.finding_id]: event.target.value }))}
                          />
                        </label>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}
        </section>

        <section aria-labelledby="pk-select" className="pk-card">
          <h2 id="pk-select" className="pk-kicker font-mono">SELECT</h2>
          <div className="fm-grid">
            <label className="text-xs text-text-2">
              {t("packaging_slot_artifact")}
              <input className="fm-input" value={slot.source_artifact_key} onChange={(event) => setSlot({ ...slot, source_artifact_key: event.target.value })} />
            </label>
            <label className="text-xs text-text-2">
              {t("packaging_slot_cohort")}
              <input className="fm-input" value={slot.cohort_id} onChange={(event) => setSlot({ ...slot, cohort_id: event.target.value })} />
            </label>
            <label className="text-xs text-text-2">
              {t("packaging_slot_surface")}
              <input className="fm-input" value={slot.product_surface} onChange={(event) => setSlot({ ...slot, product_surface: event.target.value })} />
            </label>
          </div>
          {groups.map((group) => (
            <fieldset key={group.group_id} className="pk-group">
              <legend className="text-xs text-text-2">{t("packaging_choose_variant", { group: group.group_id })}</legend>
              {group.variants.map((variant) => (
                <label key={variant.variant_id} className="mr-3 text-xs text-text-2">
                  <input
                    type="radio"
                    name={`pk-${group.group_id}`}
                    checked={choices[group.group_id] === variant.variant_id}
                    onChange={() => setChoices((current) => ({ ...current, [group.group_id]: variant.variant_id }))}
                  />{" "}
                  {variant.variant_id}
                </label>
              ))}
            </fieldset>
          ))}
          <div className="pk-actions">
            <button type="button" className="fm-btn" disabled={lockedByDraft || !observation} onClick={() => void makePreview()}>
              {t("packaging_preview")}
            </button>
            <button type="button" className="fm-btn fm-btn-accent" disabled={step.busy || !currentPreview} onClick={() => void select()}>
              {t("packaging_select")}
            </button>
          </div>
          {currentPreview ? (
            <div className="mt-2 grid gap-0.5 text-xs text-text-3" role="status">
              <p>{t("packaging_preview_ready", { expires: new Date(currentPreview.preview.expires_at).toLocaleString() })}</p>
              <p>
                {t("packaging_preview_choices", {
                  choices: currentPreview.preview.selected_variant_ids.join(", ") || t("packaging_none"),
                })}
              </p>
              <p>
                {t("packaging_preview_waivers", {
                  rules: currentPreview.preview.waivers.map((waiver) => waiver.rule_id).join(", ") || t("packaging_none"),
                })}
              </p>
            </div>
          ) : null}
          <div className="mt-2 text-xs text-text-3" role="status">
            {slotStatus.state === "loading" ? <p>{t("packaging_slot_loading")}</p> : null}
            {slotStatus.state === "failed" ? <p>{t("packaging_slot_failed")}</p> : null}
            {superseded ? <p>{t("packaging_slot_superseded")}</p> : null}
            {server && !server.selection ? <p>{t("packaging_slot_empty")}</p> : null}
            {server?.selection ? (
              <p>
                {t("packaging_slot_current", {
                  revision: server.selection.preview.candidate_revision,
                  version: server.selection.head_version,
                })}
              </p>
            ) : null}
            {server?.readiness ? (
              <p>
                {t("packaging_readiness", { state: server.readiness.state })}
                {server.readiness.disposition_decision
                  ? ` · ${t("packaging_disposition", { decision: server.readiness.disposition_decision })}`
                  : ""}
              </p>
            ) : null}
            {server?.selection && server.selection.preview.waivers.length > 0 ? (
              <p>
                {t("packaging_preview_waivers", {
                  rules: server.selection.preview.waivers.map((waiver) => waiver.rule_id).join(", "),
                })}
              </p>
            ) : null}
          </div>
          <button type="button" className="fm-btn mt-2" disabled={!slotStatus.scoped} onClick={() => void slotStatus.refresh()}>
            {t("packaging_refresh_slot")}
          </button>
        </section>

        <section aria-labelledby="pk-export" className="pk-card">
          <h2 id="pk-export" className="pk-kicker font-mono">EXPORT</h2>
          <button type="button" className="fm-btn fm-btn-accent" disabled={step.busy || !server?.exportable || !server.selection} onClick={() => void exportSelected()}>
            {t("packaging_export")}
          </button>
          {server?.selection && !server.exportable ? (
            <p className="mt-2 text-xs text-text-2" role="status">
              {t("packaging_not_exportable", { code: server.refusal_code ?? "" })}
            </p>
          ) : null}
          {receipt ? (
            <div className="mt-3">
              <p className="text-sm text-text">{t("packaging_exported", { count: receipt.manifest.entries.length })}</p>
              <ul className="pk-entries font-mono text-[11px] text-text-2">
                {receipt.manifest.entries.map((entry) => (
                  <li key={entry.path}>{entry.path}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="mt-2 text-xs text-text-3">{t("packaging_export_note")}</p>
          )}
          {server && server.exports.length > 0 ? (
            <div className="mt-3">
              <h3 className="text-xs text-text-2">{t("packaging_exports_history")}</h3>
              <ul className="pk-entries text-xs text-text-2">
                {server.exports.map((item) => (
                  <li key={`${item.selection_id}:${item.archive_digest}`} data-current={item.current}>
                    <span className="font-mono text-[11px]">{item.archive_digest.slice(7, 19)}</span>{" "}
                    {item.current ? null : <span className="text-text-3">{t("packaging_export_replaced")} </span>}
                    {item.download_token ? (
                      <a className="fm-btn inline-block" href={downloadUrl(projectName, { ...item, download_token: item.download_token })}>
                        {t("packaging_download")}
                      </a>
                    ) : (
                      <span className="text-text-3">{t("packaging_download_unavailable")}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
