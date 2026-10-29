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
  selected_candidate_id: string;
  approval_record: string;
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
  findings: { finding_id: string; rule_id: string; severity: string; subject_locator: string }[];
}

export interface RunEntry {
  run: { run_id: string; profile_id: string; profile_revision: number; subject_digest: string; sealed_at?: string };
  run_digest: string;
  disposition_version: number;
  current_disposition_id: string | null;
  cohort_id: string | null;
  product_surface: string | null;
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
): Promise<{ subject_digest: string; observations: Observation[]; more: string[] }> {
  return API.request(`${base(projectName)}/observations?${query(values)}`, { signal: options.signal });
}

export function listRuns(
  projectName: string,
  root: string,
  before: string | null,
  options: CallOptions = {},
): Promise<{ runs: RunEntry[]; next_before: string | null }> {
  const values: Record<string, string> = before ? { root, before } : { root };
  return API.request(`${base(projectName)}/runs?${query(values)}`, { signal: options.signal });
}

export function readRun(
  projectName: string,
  runId: string,
  options: CallOptions = {},
): Promise<RunEntry & { observations: Observation[] }> {
  return API.request(`${base(projectName)}/runs/${encodeURIComponent(runId)}`, { signal: options.signal });
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

export interface ProbeAttempt {
  execution_ref: string;
  execution_id: string;
  master_binding_digest: string;
  actor_id: string;
  requirement_id: string;
  attempt_state: string | null;
  observation_id: string | null;
  status: string | null;
  failure: { error_code: string; resources: Record<string, unknown> | null } | null;
}

export function listProbes(
  projectName: string,
  values: { profile_id: string; revision: number; root: string },
  after: string | null,
  options: CallOptions = {},
): Promise<{ probes: ProbeAttempt[]; next_after: string | null }> {
  return API.request(`${base(projectName)}/probes?${query(after ? { ...values, after } : values)}`, { signal: options.signal });
}

/** The actor the server seals this principal's requests for. */
export function readSession(projectName: string, options: CallOptions = {}): Promise<{ actor_id: string }> {
  return API.request(`${base(projectName)}/session`, { signal: options.signal });
}

export function listRevisions(
  projectName: string,
  profileId: string,
  options: CallOptions = {},
): Promise<{ revisions: { revision: number; profile_digest: string }[] }> {
  return API.request(`${base(projectName)}/profiles/${encodeURIComponent(profileId)}/revisions`, { signal: options.signal });
}

export function readRevision(
  projectName: string,
  profileId: string,
  revision: number,
  options: CallOptions = {},
): Promise<{ profile: Profile }> {
  return API.request(`${base(projectName)}/profiles/${encodeURIComponent(profileId)}/revisions/${revision}`, {
    signal: options.signal,
  });
}

/** Browser keeping of sealed requests until their result is shown, partitioned by project, actor, action and command. */
export function pendingPrefix(projectName: string, actor: string, action: QualityAction): string {
  return `arcreel.m10c.pending/${[projectName, actor, action].map(encodeURIComponent).join("/")}/`;
}

export function commandOf(sealed: Sealed): string {
  const command = sealed.request.command as { command_id?: unknown } | undefined;
  for (const value of [command?.command_id, sealed.request.command_id, sealed.request.execution_ref]) {
    if (typeof value === "string" && value) return value;
  }
  return "";
}
