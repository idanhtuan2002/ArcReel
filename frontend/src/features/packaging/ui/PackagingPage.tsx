/**
 * Packaging of an approved video (route `packaging`): save a package revision, run the package check, preview
 * one choice per alternative group with any allowed waivers, select it as the showrunner, then export and
 * download the archive. Every verdict, binding and refusal comes from the server; nothing here decides whether a
 * package is acceptable.
 */
import "../../formats/ui/formats.css";
import "./packaging.css";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  appendRevision,
  checkPackage,
  downloadUrl,
  exportPackage,
  newCommandId,
  previewPackage,
  selectPackage,
  type CandidateRevision,
  type ExportReceipt,
  type PackagingDraft,
  type PackagingObservation,
  type Preview,
  type Selection,
  type Slot,
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
  return { busy, error, run };
}

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
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
  const [assetsJson, setAssetsJson] = useState("[]");
  const [slot, setSlot] = useState<Slot>({ source_artifact_key: "", cohort_id: "", product_surface: "" });
  const [revision, setRevision] = useState<CandidateRevision | null>(null);
  const [headVersion, setHeadVersion] = useState<number | null>(null);
  const [observation, setObservation] = useState<PackagingObservation | null>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [receipt, setReceipt] = useState<ExportReceipt | null>(null);

  const resetAfter = (level: "revision" | "check" | "preview") => {
    if (level === "revision") {
      setObservation(null);
      setChoices({});
      setReasons({});
    }
    if (level !== "preview") setPreview(null);
    setSelection(null);
    setReceipt(null);
  };

  const saveRevision = async () => {
    let assets: PackagingDraft["assets"];
    try {
      assets = JSON.parse(assetsJson) as PackagingDraft["assets"];
    } catch {
      return void step.run(() => Promise.reject(new Error(t("packaging_assets_invalid"))), t("packaging_assets_invalid"));
    }
    const draft: PackagingDraft = {
      title,
      description,
      tags: splitList(tags),
      hashtags: splitList(hashtags),
      chapters: [],
      localization_variants: [],
      audience_classification: { audience_category: "general", age_restriction: null, classification_policy_digest: ZERO_DIGEST },
      disclosure: { synthetic_media: true, paid_promotion: false, disclosure_policy_digest: ZERO_DIGEST },
      variant_groups: [],
      assets,
    };
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
      setHeadVersion(saved.head.head_version);
      resetAfter("revision");
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
      resetAfter("check");
    }
  };

  const blocking = observation?.findings.filter((finding) => finding.severity === "BLOCKING") ?? [];

  const makePreview = async () => {
    if (!revision || !observation) return;
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
            waivers: blocking.map((finding) => ({
              rule_id: finding.rule_id,
              finding_id: finding.finding_id,
              reason: reasons[finding.finding_id] ?? "",
            })),
          },
          { signal },
        ),
      t("packaging_preview_failed"),
    );
    if (shown) {
      setPreview(shown);
      resetAfter("preview");
    }
  };

  const select = async () => {
    if (!preview) return;
    const chosen = await step.run(
      (signal) =>
        selectPackage(
          projectName,
          {
            command_id: newCommandId("select"),
            preview_id: preview.preview.preview_id,
            preview_digest: preview.preview_digest,
            expected_head_version: preview.preview.expected_head_version,
          },
          { signal },
        ),
      t("packaging_select_failed"),
    );
    if (chosen) setSelection(chosen);
  };

  const exportSelected = async () => {
    if (!selection) return;
    const exported = await step.run(
      (signal) =>
        exportPackage(
          projectName,
          { command_id: newCommandId("export"), ...slot, selection_id: selection.selection_id, selection_digest: selection.selection_digest },
          { signal },
        ),
      t("packaging_export_failed"),
    );
    if (exported) setReceipt(exported);
  };

  const ladder: { key: string; label: string; state: StepState }[] = [
    { key: "draft", label: t("packaging_step_draft"), state: revision ? "done" : "todo" },
    {
      key: "check",
      label: t("packaging_step_check"),
      state: observation ? (observation.status === "PASS" || blocking.length === 0 ? "done" : "blocked") : "todo",
    },
    { key: "select", label: t("packaging_step_select"), state: selection ? "done" : "todo" },
    { key: "export", label: t("packaging_step_export"), state: receipt ? "done" : "todo" },
  ];
  const groups = revision?.payload.variant_groups ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-bg">
      <header className="fm-header border-b border-hairline py-2.5">
        <p className="font-mono text-[10px] tracking-[0.18em] text-text-3">PROJECT · PACKAGING</p>
        <h1 className="font-editorial text-xl leading-tight text-text">{t("packaging_title")}</h1>
        <p className="mt-0.5 max-w-2xl text-xs text-text-2">{t("packaging_subtitle")}</p>
      </header>

      <ol className="pk-ladder mx-auto w-full max-w-6xl px-4 pt-5" aria-label={t("packaging_progress")}>
        {ladder.map((item, index) => (
          <li key={item.key} className="pk-rung" data-state={item.state} aria-current={item.state === "todo" ? undefined : "step"}>
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
              {t("packaging_field_assets")}
              <textarea className="fm-input font-mono" rows={3} value={assetsJson} onChange={(event) => setAssetsJson(event.target.value)} />
            </label>
          </div>
          <div className="pk-actions">
            <button type="button" className="fm-btn fm-btn-accent" disabled={step.busy || !runId || !title} onClick={() => void saveRevision()}>
              {revision ? t("packaging_save_new_revision") : t("packaging_save_revision")}
            </button>
            {revision ? (
              <p className="text-xs text-text-3" role="status">
                {t("packaging_revision_saved", { revision: revision.revision })}
              </p>
            ) : null}
          </div>
        </section>

        <section aria-labelledby="pk-check" className="pk-card">
          <h2 id="pk-check" className="pk-kicker font-mono">CHECK</h2>
          {!revision ? <p className="text-sm text-text-3">{t("packaging_check_empty")}</p> : null}
          <button type="button" className="fm-btn" disabled={step.busy || !revision || !runDigest} onClick={() => void runCheck()}>
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
            <button type="button" className="fm-btn" disabled={step.busy || !observation} onClick={() => void makePreview()}>
              {t("packaging_preview")}
            </button>
            <button type="button" className="fm-btn fm-btn-accent" disabled={step.busy || !preview} onClick={() => void select()}>
              {t("packaging_select")}
            </button>
          </div>
          {preview ? (
            <p className="text-xs text-text-3" role="status">
              {t("packaging_preview_ready", { expires: new Date(preview.preview.expires_at).toLocaleString() })}
            </p>
          ) : null}
          {selection ? (
            <p className="text-xs text-text-3" role="status">
              {t("packaging_selected", { version: selection.head_version })}
            </p>
          ) : null}
        </section>

        <section aria-labelledby="pk-export" className="pk-card">
          <h2 id="pk-export" className="pk-kicker font-mono">EXPORT</h2>
          <button type="button" className="fm-btn fm-btn-accent" disabled={step.busy || !selection} onClick={() => void exportSelected()}>
            {t("packaging_export")}
          </button>
          {receipt ? (
            <div className="mt-3">
              <p className="text-sm text-text">{t("packaging_exported", { count: receipt.manifest.entries.length })}</p>
              <ul className="pk-entries font-mono text-[11px] text-text-2">
                {receipt.manifest.entries.map((entry) => (
                  <li key={entry.path}>{entry.path}</li>
                ))}
              </ul>
              <a className="fm-btn mt-2 inline-block" href={downloadUrl(projectName, receipt)}>
                {t("packaging_download")}
              </a>
            </div>
          ) : (
            <p className="mt-2 text-xs text-text-3">{t("packaging_export_note")}</p>
          )}
        </section>
      </div>
    </div>
  );
}
