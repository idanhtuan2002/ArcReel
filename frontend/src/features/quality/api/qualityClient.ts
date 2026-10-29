/**
 * The M10-C quality routes. Every mutation is prepare/submit: the server builds and seals the complete request,
 * the page shows it for confirmation and posts it back unchanged; a failed call rejects with `ApiRequestError`.
 */

import { API } from "@/api";

interface CallOptions {
  signal?: AbortSignal;
}

export type QualityAction = "profiles" | "probes" | "reviews" | "runs" | "dispositions";

export interface Sealed {
  action: string;
  request: Record<string, unknown>;
  seal: string;
}

export interface Master {
  artifact_key: string;
  artifact_path: string;
  selected_candidate_id: string;
  resolvable: boolean;
}

export interface Profile {
  profile_id: string;
  revision: number;
  cohort_id: string;
  product_surface: string;
  profile_digest: string;
  policy: Record<string, unknown>;
}

export interface Observation {
  observation_id: string;
  observation_type: string;
  requirement_id: string;
  slot_id: string;
  status: string;
  observed_at: string;
}

export interface RunEntry {
  run: { run_id: string; profile_id: string; profile_revision: number; subject_digest: string; sealed_at?: string };
  run_digest: string;
  disposition_version: number;
  current_disposition_id: string | null;
  validity: { state: string; reasons: string[] };
  readiness: { state: string; reasons: string[] };
}

export interface TemplateQuery {
  platform_profile_id: string;
  width: number;
  height: number;
  min_duration_ms: number;
  max_duration_ms: number;
  locales: string;
}

function base(projectName: string): string {
  return `/projects/${encodeURIComponent(projectName)}/quality`;
}

function query(values: Record<string, string | number>): string {
  return new URLSearchParams(Object.entries(values).map(([key, value]) => [key, String(value)])).toString();
}

export function newCommandId(action: string): string {
  return `${action}-${crypto.randomUUID()}`;
}

export function listMasters(projectName: string, options: CallOptions = {}): Promise<{ masters: Master[] }> {
  return API.request(`${base(projectName)}/masters`, { signal: options.signal });
}

export function listProfiles(projectName: string, options: CallOptions = {}): Promise<{ profiles: Profile[] }> {
  return API.request(`${base(projectName)}/profiles`, { signal: options.signal });
}

export function profileTemplate(
  projectName: string,
  values: TemplateQuery,
  options: CallOptions = {},
): Promise<{ policy: Record<string, unknown> }> {
  return API.request(`${base(projectName)}/template?${query({ ...values })}`, { signal: options.signal });
}

export function listObservations(
  projectName: string,
  values: { profile_id: string; revision: number; root: string },
  options: CallOptions = {},
): Promise<{ subject_digest: string; observations: Observation[] }> {
  return API.request(`${base(projectName)}/observations?${query(values)}`, { signal: options.signal });
}

export function listRuns(projectName: string, root: string, options: CallOptions = {}): Promise<{ runs: RunEntry[] }> {
  return API.request(`${base(projectName)}/runs?${query({ root })}`, { signal: options.signal });
}

export function prepare(
  projectName: string,
  action: QualityAction,
  intent: Record<string, unknown>,
  options: CallOptions = {},
): Promise<Sealed> {
  return API.request(`${base(projectName)}/${action}/prepare`, {
    method: "POST",
    body: JSON.stringify(intent),
    signal: options.signal,
  });
}

export function submit(
  projectName: string,
  action: QualityAction,
  sealed: Sealed,
  options: CallOptions = {},
): Promise<Record<string, unknown>> {
  return API.request(`${base(projectName)}/${action}`, {
    method: "POST",
    body: JSON.stringify({ request: sealed.request, seal: sealed.seal }),
    signal: options.signal,
  });
}

/** Browser keeping of a sealed request until its result is shown, partitioned by project, action and command. */
export function pendingKey(projectName: string, action: QualityAction): string {
  return `arcreel.m10c.pending:${projectName}:${action}`;
}
