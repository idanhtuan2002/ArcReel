import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { controlProductionRun, newCommandId } from "../api/productionRunClient";
import type { RunSnapshot } from "../api/types";
import { SEVERITY_TONES } from "@/utils/severity-tone";

/** How long the pause question stays open before it closes by itself. */
const CONFIRM_MS = 8000;

interface Props {
  projectName: string;
  run: RunSnapshot;
  /** The run as the pause left it. */
  onPaused: (run: RunSnapshot) => void;
}

/**
 * Pauses a running automatic run in two clicks: the first asks ("Pause this run? You can resume it later."), so a
 * stray click never stops it. Usable inside a ``<summary>``: its clicks never open or close the details.
 */
export function RunPauseControl({ projectName, run, onPaused }: Props) {
  const { t } = useTranslation("workflow");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!confirming) return;
    const timer = window.setTimeout(() => setConfirming(false), CONFIRM_MS);
    return () => window.clearTimeout(timer);
  }, [confirming]);

  const keep = (event: React.SyntheticEvent) => {
    event.preventDefault();
    event.stopPropagation();
  };

  const pause = async () => {
    setConfirming(false);
    setBusy(true);
    setFailed(false);
    try {
      onPaused(
        await controlProductionRun(projectName, run.run_id, "pause", {
          command_id: newCommandId(),
          expected_version: run.version,
          expected_input_digest: run.input_digest,
          policy_digest: run.policy_digest,
        }),
      );
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {confirming ? (
        <span className="inline-flex items-center gap-2" role="group" aria-label={t("active_run_pause_confirm")}>
          <span className="text-[12px]" style={{ color: "var(--color-text-2)" }}>
            {t("active_run_pause_confirm")}
          </span>
          <button
            type="button"
            disabled={busy}
            onClick={(event) => {
              keep(event);
              void pause();
            }}
            className="focus-ring rounded-md px-2 py-0.5 text-[12px] disabled:opacity-50"
            style={{ border: `1px solid ${SEVERITY_TONES.warnings.ring}`, color: "var(--color-text)" }}
          >
            {t("active_run_pause_yes")}
          </button>
          <button
            type="button"
            onClick={(event) => {
              keep(event);
              setConfirming(false);
            }}
            className="focus-ring rounded-md px-2 py-0.5 text-[12px]"
            style={{ color: "var(--color-text-2)" }}
          >
            {t("active_run_pause_no")}
          </button>
        </span>
      ) : (
        <button
          type="button"
          disabled={busy}
          onClick={(event) => {
            keep(event);
            setConfirming(true);
          }}
          className="focus-ring rounded-md px-2 py-0.5 text-[12px] disabled:opacity-50"
          style={{ border: "1px solid var(--color-hairline)", color: "var(--color-text)" }}
        >
          {t("active_run_pause")}
        </button>
      )}
      {failed && (
        <span role="alert" className="text-[12px]" style={{ color: SEVERITY_TONES.blocking.color }}>
          {t("outcome_action_failed")}
        </span>
      )}
    </span>
  );
}
