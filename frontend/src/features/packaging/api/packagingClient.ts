/**
 * The M10-B packaging routes: candidate revisions, checks, previews, showrunner selection, export and download.
 * The server builds every command, binding and provenance; a failed call rejects with `ApiRequestError`.
 */

import { API } from "@/api";

interface CallOptions {
  signal?: AbortSignal;
}

export type Severity = "BLOCKING" | "ADVISORY";

export interface PackagingDraft {
  title: string;
  description: string;
  tags: string[];
  hashtags: string[];
  chapters: { start_ms: number; title: string }[];
  localization_variants: unknown[];
  audience_classification: { audience_category: string; age_restriction: string | null; classification_policy_digest: string };
  disclosure: { synthetic_media: boolean; paid_promotion: boolean; disclosure_policy_digest: string };
  variant_groups: unknown[];
  assets: {
    role: string;
    variant_id: string | null;
    source_ref: string;
    content_digest: string;
    media_type: string;
    byte_size: number;
    constraint_rule_id: string;
  }[];
}

export interface CandidateRevision {
  candidate_id: string;
  revision: number;
  payload_digest: string;
  payload: { variant_groups: { group_id: string; field: string; variants: { variant_id: string }[] }[] };
}

export interface Finding {
  finding_id: string;
  rule_id: string;
  severity: Severity;
  subject_locator: string;
}

export interface PackagingObservation {
  observation_id: string;
  status: "PASS" | "FAIL";
  findings: Finding[];
}

export interface Slot {
  source_artifact_key: string;
  cohort_id: string;
  product_surface: string;
}

export interface Waiver {
  rule_id: string;
  finding_id: string;
  reason: string;
}

export interface Preview {
  preview: {
    preview_id: string;
    expected_head_version: number;
    expires_at: string;
    candidate_revision: number;
    selected_variant_ids: string[];
    waivers: Waiver[];
  };
  preview_digest: string;
}

export interface Selection {
  selection_id: string;
  selection_digest: string;
  head_version: number;
  preview: Preview["preview"];
}

export interface ExportReceipt {
  archive_digest: string;
  archive_byte_size: number;
  status: "EXPORTED";
  download_token: string;
  manifest: { entries: { path: string; byte_size: number; content_digest: string }[] };
}

/** The slot as the server sees it now; `download_token` is null whenever downloading would be refused. */
export interface SlotStatus {
  head_version: number;
  exportable: boolean;
  refusal_code: string | null;
  selection: Selection | null;
  exports: (Omit<ExportReceipt, "download_token"> & { download_token: string | null; exported_at: string })[];
}

function base(projectName: string): string {
  return `/projects/${encodeURIComponent(projectName)}/packaging`;
}

function post<T>(endpoint: string, body: unknown, options: CallOptions): Promise<T> {
  return API.request(endpoint, { method: "POST", body: JSON.stringify(body), signal: options.signal });
}

/** A fresh command id per user action, so a retried click never reuses another action's id. */
export function newCommandId(action: string): string {
  return `${action}-${crypto.randomUUID()}`;
}

export function appendRevision(
  projectName: string,
  body: { command_id: string; quality_run_id: string; candidate_id: string | null; expected_head_version: number | null; draft: PackagingDraft },
  options: CallOptions = {},
): Promise<{ revision: CandidateRevision; head: { head_version: number } }> {
  return post(`${base(projectName)}/revisions`, body, options);
}

export function checkPackage(
  projectName: string,
  body: {
    command_id: string;
    candidate_id: string;
    candidate_revision: number;
    candidate_payload_digest: string;
    quality_run_id: string;
    quality_run_digest: string;
  },
  options: CallOptions = {},
): Promise<PackagingObservation> {
  return post(`${base(projectName)}/checks`, body, options);
}

export function previewPackage(
  projectName: string,
  body: Slot & {
    command_id: string;
    candidate_id: string;
    candidate_revision: number;
    candidate_payload_digest: string;
    packaging_observation_id: string;
    selected_variant_ids: string[];
    waivers: Waiver[];
  },
  options: CallOptions = {},
): Promise<Preview> {
  return post(`${base(projectName)}/previews`, body, options);
}

export function selectPackage(
  projectName: string,
  body: { command_id: string; preview_id: string; preview_digest: string; expected_head_version: number },
  options: CallOptions = {},
): Promise<Selection> {
  return post(`${base(projectName)}/selections`, body, options);
}

export function exportPackage(
  projectName: string,
  body: Slot & { command_id: string; selection_id: string; selection_digest: string },
  options: CallOptions = {},
): Promise<ExportReceipt> {
  return post(`${base(projectName)}/exports`, body, options);
}

export function getSlotStatus(projectName: string, slot: Slot, options: CallOptions = {}): Promise<SlotStatus> {
  const query = new URLSearchParams({ ...slot }).toString();
  return API.request(`${base(projectName)}/slot?${query}`, { signal: options.signal });
}

export function downloadUrl(projectName: string, receipt: { archive_digest: string; download_token: string }): string {
  const hex = receipt.archive_digest.replace(/^sha256:/, "");
  return `/api/v1${base(projectName)}/exports/${hex}/archive?token=${encodeURIComponent(receipt.download_token)}`;
}
