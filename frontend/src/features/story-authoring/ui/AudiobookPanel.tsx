import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  downloadAudiobook,
  listAudiobooks,
  startAudiobook,
  type AudiobookFileKind,
  type AudiobookJob,
  type AudiobookPreset,
} from "../api/storyClient";

const POLL_MS = 5_000;
const PRESETS: AudiobookPreset[] = ["standard", "sleep"];
const EXTENSION: Record<AudiobookFileKind, string> = { m4b: "m4b", mp3: "mp3", mp4: "mp4", chapters: "txt" };

/** ADR-0159: the committed story as an audiobook or a sleep story, spoken with the project's narration voice. */
export function AudiobookPanel({ projectName, runId, title }: { projectName: string; runId: string; title: string }) {
  const { t } = useTranslation("dashboard");
  const [jobs, setJobs] = useState<AudiobookJob[]>([]);
  const [failed, setFailed] = useState(false);
  const [starting, setStarting] = useState<AudiobookPreset | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listAudiobooks(projectName, runId, { signal: controller.signal })
      .then((next) => {
        if (!controller.signal.aborted) setJobs(next);
      })
      .catch(() => {
        // A failed refresh keeps the last known jobs; the next poll tries again.
      });
    return () => controller.abort();
  }, [projectName, runId, tick]);

  const running = jobs.some((job) => job.state === "running");
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setTick((n) => n + 1), POLL_MS);
    return () => window.clearInterval(timer);
  }, [running]);

  async function start(preset: AudiobookPreset) {
    setStarting(preset);
    setFailed(false);
    try {
      await startAudiobook(projectName, runId, preset);
      setTick((n) => n + 1);
    } catch {
      setFailed(true);
    } finally {
      setStarting(null);
    }
  }

  async function save(job: AudiobookJob, kind: AudiobookFileKind) {
    try {
      const blob = await downloadAudiobook(projectName, runId, job.preset, kind);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${title}-${job.preset}.${EXTENSION[kind]}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setFailed(true);
    }
  }

  return (
    <div className="mt-3 text-xs text-text-2">
      <p>{t("story_audiobook_hint")}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {PRESETS.map((preset) => {
          const job = jobs.find((j) => j.preset === preset);
          return (
            <button
              key={preset}
              type="button"
              className="sa-btn"
              disabled={starting !== null || job?.state === "running"}
              onClick={() => void start(preset)}
            >
              {t(`story_audiobook_${preset}`)}
            </button>
          );
        })}
      </div>
      {jobs.map((job) => (
        <div key={job.preset} className="mt-2 flex flex-wrap items-center gap-2" role="status">
          <span>{t(`story_audiobook_${job.preset}`)}:</span>
          {job.state === "running" ? (
            <span>{t("story_audiobook_running", { done: job.done, total: job.total || "…" })}</span>
          ) : null}
          {job.state === "failed" ? <span role="alert">{t("story_audiobook_failed")}</span> : null}
          {job.state === "done"
            ? job.files.map((kind) => (
                <button key={kind} type="button" className="sa-btn" onClick={() => void save(job, kind)}>
                  {t(`story_audiobook_file_${kind}`)}
                </button>
              ))
            : null}
        </div>
      ))}
      {failed ? <p role="alert">{t("story_audiobook_failed")}</p> : null}
    </div>
  );
}
