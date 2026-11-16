import { useState } from "react";
import { useTranslation } from "react-i18next";
import { RotateCcw } from "lucide-react";
import { API } from "@/api";
import { useProjectsStore } from "@/stores/projects-store";
import { SEVERITY_TONES } from "@/utils/severity-tone";

interface ResetResult {
  confirmation_required: boolean;
  consumed_episodes: number[];
  removed_episodes: number[];
  deleted_files: string[];
  archived_files: unknown[];
}

function resetEpisodePlanning(projectName: string, fromEpisode: number, confirmConsumed: boolean): Promise<ResetResult> {
  return API.request(`/projects/${encodeURIComponent(projectName)}/episode-planning/reset`, {
    method: "POST",
    body: JSON.stringify({ from_episode: fromEpisode, confirm_consumed: confirmConsumed }),
  });
}

interface Props {
  projectName: string;
  /** The highest planned episode number; the reset starts at an episode of the plan. */
  lastEpisode: number;
}

/**
 * Clears the episode plan from a chosen episode on so the rest of the source is planned again. When the reset would
 * clear episodes that already have scripts or media, the server changes nothing and names them; the user confirms
 * once more. Scripts and media stay on disk.
 */
export function ResetEpisodePlanning({ projectName, lastEpisode }: Props) {
  const { t } = useTranslation("dashboard");
  const refreshProject = useProjectsStore((s) => s.refreshProject);
  const [open, setOpen] = useState(false);
  // The typed text; it is read as an episode number only when the reset is sent, so typing is never rewritten.
  const [fromText, setFromText] = useState("1");
  const fromEpisode = Math.min(Math.max(1, Math.trunc(Number(fromText)) || 1), Math.max(1, lastEpisode));
  const [consumed, setConsumed] = useState<number[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const close = () => {
    setOpen(false);
    setConsumed(null);
    setMessage(null);
    setFailed(false);
  };

  const run = async (confirmConsumed: boolean) => {
    setBusy(true);
    setFailed(false);
    setMessage(null);
    try {
      const result = await resetEpisodePlanning(projectName, fromEpisode, confirmConsumed);
      if (result.confirmation_required) {
        setConsumed(result.consumed_episodes);
        return;
      }
      setConsumed(null);
      setMessage(t("reset_planning_done", { count: result.removed_episodes.length }));
      await refreshProject(projectName);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => (open ? close() : setOpen(true))}
        disabled={lastEpisode < 1}
        className="grid h-5 w-5 place-items-center rounded focus-ring disabled:cursor-not-allowed disabled:opacity-50"
        style={{ background: "var(--color-surface-2)", color: "var(--color-text-3)" }}
        title={t("reset_planning")}
        aria-label={t("reset_planning")}
        aria-expanded={open}
      >
        <RotateCcw className="h-3 w-3" />
      </button>
      {open && (
        <div
          role="dialog"
          aria-label={t("reset_planning")}
          className="absolute left-2.5 right-2.5 top-9 z-20 space-y-2 rounded-md p-2.5 text-[11.5px]"
          style={{
            background: "var(--color-surface-2)",
            border: "1px solid var(--color-hairline)",
            color: "var(--color-text-2)",
          }}
        >
          <p className="m-0">{t("reset_planning_hint")}</p>
          <label className="flex items-center gap-2">
            <span>{t("reset_planning_from")}</span>
            <input
              type="number"
              min={1}
              max={lastEpisode}
              value={fromText}
              onChange={(e) => {
                setFromText(e.target.value);
                setConsumed(null);
              }}
              className="w-14 rounded bg-transparent px-1.5 py-0.5 focus-ring"
              style={{ border: "1px solid var(--color-hairline)", color: "var(--color-text)" }}
            />
          </label>
          {consumed && (
            <p className="m-0" style={{ color: SEVERITY_TONES.warnings.color }}>
              {t("reset_planning_consumed", { episodes: consumed.join(", ") })}
            </p>
          )}
          {message && <p className="m-0">{message}</p>}
          {failed && (
            <p className="m-0" style={{ color: SEVERITY_TONES.blocking.color }}>
              {t("reset_planning_failed")}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" className="rounded px-2 py-1 focus-ring" onClick={close}>
              {t("reset_planning_close")}
            </button>
            <button
              type="button"
              disabled={busy}
              className="rounded px-2 py-1 focus-ring disabled:opacity-50"
              style={{ background: "var(--color-accent-dim)", color: "var(--color-text)" }}
              onClick={() => void run(consumed !== null)}
            >
              {consumed ? t("reset_planning_confirm") : t("reset_planning_run")}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
