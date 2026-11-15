import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { downloadTrailer, getTrailer, startTrailer, type TrailerJob } from "../api/productionRunClient";

const POLL_MS = 5_000;
const BUTTON_CLS = "focus-ring rounded-md px-2.5 py-1 text-[12px] disabled:opacity-50 hover:opacity-90";
const BUTTON_STYLE = { border: "1px solid var(--color-hairline-strong)", color: "var(--color-text-2)" };

/** ADR-0164: a trailer cut from the run's verified finals — hook, escalation and a tease, never the ending. */
export function TrailerPanel({ projectName, runId }: { projectName: string; runId: string }) {
  const { t } = useTranslation("workflow");
  const [job, setJob] = useState<TrailerJob | null>(null);
  const [failed, setFailed] = useState(false);
  const [starting, setStarting] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getTrailer(projectName, runId, { signal: controller.signal })
      .then((next) => {
        if (!controller.signal.aborted) setJob(next);
      })
      .catch(() => {
        // A failed refresh keeps the last known state; the next poll tries again.
      });
    return () => controller.abort();
  }, [projectName, runId, tick]);

  const running = job?.state === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setTick((n) => n + 1), POLL_MS);
    return () => window.clearInterval(timer);
  }, [running]);

  async function start() {
    setStarting(true);
    setFailed(false);
    try {
      setJob(await startTrailer(projectName, runId));
    } catch {
      setFailed(true);
    } finally {
      setStarting(false);
    }
  }

  async function save() {
    try {
      const blob = await downloadTrailer(projectName, runId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${projectName}-trailer.mp4`;
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setFailed(true);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-[12px]" style={{ color: "var(--color-text-2)" }}>
      <span>{t("auto_trailer_hint")}</span>
      <button
        type="button"
        className={BUTTON_CLS}
        style={BUTTON_STYLE}
        disabled={starting || running}
        onClick={() => void start()}
      >
        {running ? t("auto_trailer_running") : job?.state === "done" ? t("auto_trailer_again") : t("auto_trailer_make")}
      </button>
      {job?.state === "done" && (
        <button type="button" className={BUTTON_CLS} style={BUTTON_STYLE} onClick={() => void save()}>
          {t("auto_trailer_download", { seconds: Math.round(job.duration ?? 0) })}
        </button>
      )}
      {job?.state === "failed" && (
        <span role="alert" style={{ color: "var(--color-warn)" }}>
          {t("auto_trailer_failed", { reason: job.error ?? "" })}
        </span>
      )}
      {failed && (
        <span role="alert" style={{ color: "var(--color-warn)" }}>
          {t("auto_trailer_request_failed")}
        </span>
      )}
    </div>
  );
}
