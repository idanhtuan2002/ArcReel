import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { SEVERITY_TONES } from "@/utils/severity-tone";
import { getAutomationReadiness } from "../api/productionRunClient";
import type { Readiness } from "../api/types";

interface Props {
  projectName: string;
}

/**
 * The project's automatic production setup and whether a Start would pass preflight now.
 *
 * Preflight probes the GPU, disk and model inventory, so it runs when the section is opened or re-checked, never on
 * the panel's poll.
 */
export function AutomationReadiness({ projectName }: Props) {
  const { t } = useTranslation("workflow");
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [checking, setChecking] = useState(false);
  const [failed, setFailed] = useState(false);

  const check = useCallback(async () => {
    setChecking(true);
    setFailed(false);
    try {
      setReadiness(await getAutomationReadiness(projectName));
    } catch {
      setFailed(true);
    } finally {
      setChecking(false);
    }
  }, [projectName]);

  const reasonText = (code: string) => t(`auto_reason_${code}`, { defaultValue: code });
  return (
    <details
      className="text-[12px]"
      onToggle={(event) => {
        if ((event.currentTarget).open && readiness === null && !checking) void check();
      }}
    >
      <summary className="cursor-pointer" style={{ color: "var(--color-text-2)" }}>
        {t("auto_setup_title")}
      </summary>
      <div className="mt-1 space-y-1.5">
        {checking && <p style={{ color: "var(--color-text-3)" }}>{t("auto_setup_checking")}</p>}
        {failed && <p style={{ color: SEVERITY_TONES.blocking.color }}>{t("auto_setup_failed")}</p>}
        {readiness && (
          <>
            <p style={{ color: readiness.ready ? "var(--color-accent-2)" : SEVERITY_TONES.warnings.color }}>
              {readiness.ready ? t("auto_setup_ready") : t("auto_setup_not_ready")}
            </p>
            {readiness.reasons.length > 0 && (
              <ul className="m-0 list-disc space-y-0.5 pl-5" style={{ color: SEVERITY_TONES.warnings.color }}>
                {readiness.reasons.map((reason) => (
                  <li key={reason}>{reasonText(reason)}</li>
                ))}
              </ul>
            )}
            {readiness.routes.length > 0 && (
              <table className="w-full text-left text-[11.5px]">
                <tbody>
                  {readiness.routes.map((route) => (
                    <tr key={route.role}>
                      <td className="pr-3" style={{ color: "var(--color-text-2)" }}>
                        {t(`auto_role_${route.role}`, { defaultValue: route.role })}
                      </td>
                      <td className="pr-3 font-mono" style={{ color: "var(--color-text-3)" }}>
                        {route.model_id}
                      </td>
                      <td style={{ color: "var(--color-text-3)" }}>
                        {route.paid
                          ? t("auto_setup_paid", { limit: route.max_cost_per_call ?? "–" })
                          : route.local
                            ? t("auto_setup_local")
                            : t("auto_setup_cloud")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {readiness.limits && (
              <p style={{ color: "var(--color-text-3)" }}>
                {t("auto_setup_limits", {
                  calls: readiness.limits.max_model_calls,
                  hours: Math.round(readiness.limits.max_runtime_seconds / 360) / 10,
                  episodes: readiness.limits.max_target_episodes,
                  cost: readiness.limits.max_cost_minor_units,
                  currency: readiness.limits.currency,
                })}
                {readiness.quality_gate === "record" ? ` · ${t("auto_setup_record_gate")}` : ""}
              </p>
            )}
          </>
        )}
        <button
          type="button"
          className="focus-ring rounded text-[11.5px] underline underline-offset-2 hover:opacity-80 disabled:opacity-50"
          disabled={checking}
          onClick={() => void check()}
        >
          {t("auto_setup_recheck")}
        </button>
      </div>
    </details>
  );
}
