import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useAppStore } from "@/stores/app-store";
import { listVideoSources, startVideoSource, type VideoSourceJob } from "../api/storyClient";

const POLL_MS = 4_000;

/** ADR-0161: import a video by URL as a story source; its transcript is the material of a transformed variant. */
export function VideoSourceImport({ projectName }: { projectName: string }) {
  const { t } = useTranslation("dashboard");
  const invalidateSourceFiles = useAppStore((s) => s.invalidateSourceFiles);
  const [url, setUrl] = useState("");
  const [jobs, setJobs] = useState<VideoSourceJob[]>([]);
  const [tick, setTick] = useState(0);
  const [failed, setFailed] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    listVideoSources(projectName, { signal: controller.signal })
      .then((next) => {
        if (controller.signal.aborted) return;
        setJobs((previous) => {
          const finished = next.some(
            (job) => job.state === "done" && previous.some((p) => p.url === job.url && p.state === "running"),
          );
          if (finished) invalidateSourceFiles();
          return next;
        });
      })
      .catch(() => {
        // The next poll tries again.
      });
    return () => controller.abort();
  }, [projectName, tick, invalidateSourceFiles]);

  const running = jobs.some((job) => job.state === "running");
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setTick((n) => n + 1), POLL_MS);
    return () => window.clearInterval(timer);
  }, [running]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!url.trim()) return;
    setSending(true);
    setFailed(false);
    try {
      await startVideoSource(projectName, url.trim());
      setUrl("");
      setTick((n) => n + 1);
    } catch {
      setFailed(true);
    } finally {
      setSending(false);
    }
  }

  return (
    <form className="mb-4 rounded-md border border-hairline p-3 text-[12px]" onSubmit={(e) => void submit(e)}>
      <label className="flex flex-col gap-1.5">
        <span className="text-text-2">{t("video_source_label")}</span>
        <span className="flex gap-2">
          <input
            type="url"
            className="sa-input flex-1"
            placeholder="https://"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
          />
          <button type="submit" className="sa-btn" disabled={sending || !url.trim()}>
            {t("video_source_import")}
          </button>
        </span>
      </label>
      <p className="mt-1.5 text-[11px] text-text-3">{t("video_source_hint")}</p>
      {jobs.map((job) => (
        <p key={job.url} className="mt-1 text-text-2" role="status">
          {job.title ?? job.url}: {t(`video_source_state_${job.state === "running" ? job.step : job.state}`)}
          {job.state === "failed" && job.error ? ` (${job.error})` : null}
        </p>
      ))}
      {failed ? (
        <p role="alert" className="mt-1 text-danger">
          {t("video_source_failed")}
        </p>
      ) : null}
    </form>
  );
}
