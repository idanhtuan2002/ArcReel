import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { STOPPED, TERMINAL, type RunSnapshot } from "./api/types";
import { describeReason } from "./reasonCopy";
import { useProjectRuns } from "./runsStore";
import { useAppStore } from "@/stores/app-store";
import type { WorkspaceNotificationInput } from "@/types/workspace";

const SENT_KEY = "arcreel.runNotifications.sent";

function sent(): Set<string> {
  try {
    return new Set(JSON.parse(window.sessionStorage.getItem(SENT_KEY) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

function remember(keys: Set<string>): void {
  try {
    window.sessionStorage.setItem(SENT_KEY, JSON.stringify([...keys].slice(-200)));
  } catch {
    // Private mode or quota: a notification may then repeat after a reload.
  }
}

/** What a filmmaker needs to hear about a run's latest state, or ``null`` when nothing worth a notification. */
export function runNotification(
  run: RunSnapshot,
  t: (key: string, options?: Record<string, unknown>) => string,
): WorkspaceNotificationInput | null {
  const episode = Number((run.targets[0] ?? "episode:0").split(":")[1]) || null;
  const stage = t(`auto_stage_${run.stage}`, { ns: "workflow" });
  const target = { type: "run_controls" as const, id: run.run_id, route: "/" };
  if (run.status === "SUCCEEDED") {
    return { text: t("run_note_done", { ns: "workflow", episode }), tone: "success", target };
  }
  if (STOPPED.has(run.status) || run.status === "FAILED" || run.status === "FAILED_QUALITY") {
    const reason = run.reason
      ? describeReason(t as never, run.reason).text
      : t(`auto_status_${run.status}`, { ns: "workflow" });
    return {
      text: t("run_note_stopped", { ns: "workflow", episode, stage, reason }),
      tone: run.status.startsWith("FAILED") ? "error" : "warning",
      target,
    };
  }
  if (!TERMINAL.has(run.status)) {
    return { text: t("run_note_stage", { ns: "workflow", episode, stage }), tone: "info", target, read: true };
  }
  return null;
}

/**
 * Tells the workspace notifications what the project's automatic run is doing: each new stage, a stop that needs the
 * filmmaker (with its reason in plain words) and a finished film. Each notification opens the run's controls. A
 * state is announced once per browser session; a stop found when the page opens is announced too.
 */
export function useRunNotifications(projectName: string | null): void {
  const { t } = useTranslation("workflow");
  const runs = useProjectRuns(projectName);
  const pushWorkspaceNotification = useAppStore((s) => s.pushWorkspaceNotification);
  const seen = useRef<string | null>(null);
  const latest = runs?.[0] ?? null;
  const key = latest ? `${projectName}:${latest.run_id}:${latest.status}:${latest.stage}` : null;

  useEffect(() => {
    if (!latest || !key || seen.current === key) return;
    const first = seen.current === null;
    seen.current = key;
    const announced = sent();
    if (announced.has(key)) return;
    const note = runNotification(latest, t);
    // On opening the page only a stop or a finished film is news; the stage a run is in is shown on the page.
    if (!note || (first && note.tone === "info")) return;
    announced.add(key);
    remember(announced);
    pushWorkspaceNotification(note);
  }, [key, latest, t, pushWorkspaceNotification]);
}
