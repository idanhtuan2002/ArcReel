/**
 * Production run routes: list with the start offer, Start, read, Pause/Resume/Cancel, mode change, checkpoint review
 * and the verified archive download. A failed call rejects with `ApiRequestError`.
 */

import { API } from "@/api";
import type {
  AutomationMode,
  AutomationSettings,
  AutomationSettingsUpdate,
  AutomationSettingsView,
  Checkpoint,
  Readiness,
  RunList,
  RunReport,
  RunSnapshot,
} from "./types";

interface CallOptions {
  signal?: AbortSignal;
}

const base = (projectName: string) => `/projects/${encodeURIComponent(projectName)}/production-runs`;

export interface StartCommand {
  command_id: string;
  mode: AutomationMode;
  idea: string;
  targets: string[];
  expected_input_digest: string;
  policy_digest: string;
}

export interface ControlCommand {
  command_id: string;
  expected_version: number;
  expected_input_digest: string;
  policy_digest: string;
}

export type ControlAction = "pause" | "resume" | "cancel";

export function newCommandId(): string {
  return `cmd-${crypto.randomUUID()}`;
}

export function listProductionRuns(projectName: string, options: CallOptions = {}): Promise<RunList> {
  return API.request<RunList>(base(projectName), { signal: options.signal });
}

export function startProductionRun(
  projectName: string,
  command: StartCommand,
  options: CallOptions = {},
): Promise<RunSnapshot> {
  return API.request<RunSnapshot>(base(projectName), {
    method: "POST",
    body: JSON.stringify(command),
    signal: options.signal,
  });
}

export function getProductionRun(projectName: string, runId: string, options: CallOptions = {}): Promise<RunSnapshot> {
  return API.request<RunSnapshot>(`${base(projectName)}/${encodeURIComponent(runId)}`, { signal: options.signal });
}

export function getAutomationReadiness(projectName: string, options: CallOptions = {}): Promise<Readiness> {
  return API.request<Readiness>(`/projects/${encodeURIComponent(projectName)}/automation/readiness`, {
    signal: options.signal,
  });
}

export function getAutomationSettings(projectName: string, options: CallOptions = {}): Promise<AutomationSettings> {
  return API.request<AutomationSettings>(`/projects/${encodeURIComponent(projectName)}/automation/settings`, {
    signal: options.signal,
  });
}

export function saveAutomationSettings(
  projectName: string,
  update: AutomationSettingsUpdate,
  options: CallOptions = {},
): Promise<AutomationSettingsView> {
  return API.request<AutomationSettingsView>(`/projects/${encodeURIComponent(projectName)}/automation/settings`, {
    method: "PUT",
    body: JSON.stringify(update),
    signal: options.signal,
  });
}

export function getProductionRunReport(
  projectName: string,
  runId: string,
  options: CallOptions = {},
): Promise<RunReport> {
  return API.request<RunReport>(`${base(projectName)}/${encodeURIComponent(runId)}/report`, {
    signal: options.signal,
  });
}

export function controlProductionRun(
  projectName: string,
  runId: string,
  action: ControlAction,
  command: ControlCommand,
  options: CallOptions = {},
): Promise<RunSnapshot> {
  return API.request<RunSnapshot>(`${base(projectName)}/${encodeURIComponent(runId)}/${action}`, {
    method: "POST",
    body: JSON.stringify(command),
    signal: options.signal,
  });
}

export function changeProductionRunMode(
  projectName: string,
  runId: string,
  command: ControlCommand & { mode: AutomationMode },
  options: CallOptions = {},
): Promise<RunSnapshot> {
  return API.request<RunSnapshot>(`${base(projectName)}/${encodeURIComponent(runId)}/mode`, {
    method: "POST",
    body: JSON.stringify(command),
    signal: options.signal,
  });
}

export function reviewProductionRun(
  projectName: string,
  runId: string,
  command: {
    command_id: string;
    expected_version: number;
    checkpoint: Checkpoint;
    binding_digest: string;
    decision: "APPROVE" | "REJECT";
  },
  options: CallOptions = {},
): Promise<RunSnapshot> {
  return API.request<RunSnapshot>(`${base(projectName)}/${encodeURIComponent(runId)}/review`, {
    method: "POST",
    body: JSON.stringify(command),
    signal: options.signal,
  });
}

export async function downloadProductionOutput(
  projectName: string,
  runId: string,
  episode: number,
  options: CallOptions = {},
): Promise<Blob> {
  const response = await API.requestBinary(
    `${base(projectName)}/${encodeURIComponent(runId)}/outputs/${episode}`,
    { signal: options.signal },
  );
  return response.blob();
}
