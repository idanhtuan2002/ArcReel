import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiRequestError } from "@/api";
import { SEVERITY_TONES } from "@/utils/severity-tone";
import {
  getQualification,
  recordLaunchQualification,
  startMediaProbes,
} from "../api/productionRunClient";
import type { MediaRouteStatus, QualificationStatus } from "../api/types";
import { HelpHint } from "@/components/ui/HelpHint";

const POLL_MS = 5000;
const LINK_CLS =
  "focus-ring rounded text-[11.5px] underline underline-offset-2 hover:opacity-80 disabled:opacity-50 disabled:hover:opacity-50";

interface Props {
  projectName: string;
  /** Called after a probe job ends or the launch is recorded, so readiness is checked again. */
  onChanged?: () => void;
}

/**
 * Probe media routes outside the launch profile and record the launch, then follow the jobs. Reviewers are trusted by
 * configuration and have no qualification (ADR-0169). Read when opened; polled only while a probe job runs.
 */
export function AutomationQualification({ projectName, onChanged }: Props) {
  const { t } = useTranslation("workflow");
  const [status, setStatus] = useState<QualificationStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const refusal = useCallback(
    (cause: unknown) => {
      const code = cause instanceof ApiRequestError && cause.code ? cause.code : null;
      return code ? t(`auto_reason_${code}`, { defaultValue: code }) : t("auto_qual_failed");
    },
    [t],
  );

  const load = useCallback(async () => {
    try {
      setStatus(await getQualification(projectName));
    } catch (cause) {
      setMessage({ ok: false, text: refusal(cause) });
    }
  }, [projectName, refusal]);

  const media = status?.media ?? [];
  const running = media.some((route) => route.job?.state === "running");
  const unprobed = media.some((route) => !route.profile_route && route.probe?.passed !== true);
  useEffect(() => {
    if (!open || !running) return;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [open, running, load]);
  // A job that was running and has ended changes readiness; report it once.
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !running) onChanged?.();
    wasRunning.current = running;
  }, [running, onChanged]);

  const probeMedia = async () => {
    setBusy(true);
    setMessage(null);
    try {
      setStatus(await startMediaProbes(projectName));
    } catch (cause) {
      setMessage({ ok: false, text: refusal(cause) });
    } finally {
      setBusy(false);
    }
  };

  const mediaState = (route: MediaRouteStatus): { ok: boolean; text: string } => {
    if (route.job?.state === "running") return { ok: false, text: t("auto_qual_media_running") };
    if (route.profile_route) return { ok: true, text: t("auto_qual_media_profile") };
    if (route.probe?.passed) return { ok: true, text: t("auto_qual_media_passed") };
    if (route.probe) {
      return { ok: false, text: t("auto_qual_media_failed", { problem: route.probe.error ?? route.probe.problem ?? "" }) };
    }
    return { ok: false, text: t("auto_qual_media_missing") };
  };

  const recordLaunch = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await recordLaunchQualification(projectName);
      setMessage(
        result.recorded
          ? { ok: true, text: t("auto_qual_launch_recorded") }
          : {
              ok: false,
              text: t("auto_qual_launch_blocked", {
                reasons: result.reasons.map((r) => t(`auto_reason_${r}`, { defaultValue: r })).join(", "),
              }),
            },
      );
      await load();
      if (result.recorded) onChanged?.();
    } catch (cause) {
      setMessage({ ok: false, text: refusal(cause) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <details
      className="text-[12px]"
      onToggle={(event) => {
        const opened = (event.currentTarget).open;
        setOpen(opened);
        if (opened && status === null) void load();
      }}
    >
      <summary className="cursor-pointer" style={{ color: "var(--color-text-2)" }}>
        {t("auto_qual_title")}{" "}
        <HelpHint topic={t("auto_qual_title")}>{t("help_qualification")}</HelpHint>
      </summary>
      <div className="mt-1 space-y-1.5">
        {status && (
          <>
            {media.length > 0 && (
              <ul className="m-0 list-none space-y-1 p-0">
                {media.map((route) => {
                  const state = mediaState(route);
                  return (
                    <li key={route.role}>
                      <span style={{ color: "var(--color-text-2)" }}>
                        {t(`auto_role_${route.role}`, { defaultValue: route.role })}
                      </span>{" "}
                      <span className="font-mono text-[11px]" style={{ color: "var(--color-text-3)" }}>
                        {route.model_id}
                      </span>{" "}
                      <span style={{ color: state.ok ? "var(--color-accent-2)" : SEVERITY_TONES.warnings.color }}>
                        {state.text}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
            <p style={{ color: status.launch_recorded ? "var(--color-accent-2)" : "var(--color-text-3)" }}>
              {status.launch_recorded ? t("auto_qual_launch_ok") : t("auto_qual_launch_missing")}
            </p>
            {unprobed && !status.receipts_configured && (
              <p style={{ color: SEVERITY_TONES.warnings.color }}>{t("auto_qual_no_receipts")}</p>
            )}
            <div className="flex flex-wrap gap-3">
              {unprobed && (
                <button
                  type="button"
                  className={LINK_CLS}
                  disabled={busy || running || !status.receipts_configured}
                  onClick={() => void probeMedia()}
                >
                  {t("auto_qual_start_media")}
                </button>
              )}
              <button
                type="button"
                className={LINK_CLS}
                disabled={busy || running || !status.evidence_configured}
                onClick={() => void recordLaunch()}
              >
                {t("auto_qual_record_launch")}
              </button>
            </div>
            <p style={{ color: "var(--color-text-3)" }}>{t("auto_qual_hint")}</p>
            {unprobed && <p style={{ color: "var(--color-text-3)" }}>{t("auto_qual_media_hint")}</p>}
          </>
        )}
        {message && (
          <p role="status" style={{ color: message.ok ? "var(--color-accent-2)" : SEVERITY_TONES.blocking.color }}>
            {message.text}
          </p>
        )}
      </div>
    </details>
  );
}
