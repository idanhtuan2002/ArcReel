import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useAppStore } from "@/stores/app-store";
import { listDocumentaries, startDocumentary, type DocumentaryJob } from "../api/storyClient";

const POLL_MS = 5_000;
const LANGUAGES: DocumentaryJob["language"][] = ["vi", "en", "zh"];

/** ADR-0162: a topic researched on public references becomes a cited documentary narration (a story source). */
export function DocumentaryImport({ projectName }: { projectName: string }) {
  const { t } = useTranslation("dashboard");
  const invalidateSourceFiles = useAppStore((s) => s.invalidateSourceFiles);
  const [topic, setTopic] = useState("");
  const [language, setLanguage] = useState<DocumentaryJob["language"]>("vi");
  const [jobs, setJobs] = useState<DocumentaryJob[]>([]);
  const [tick, setTick] = useState(0);
  const [failed, setFailed] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    listDocumentaries(projectName, { signal: controller.signal })
      .then((next) => {
        if (controller.signal.aborted) return;
        setJobs((previous) => {
          const finished = next.some(
            (job) => job.state === "done" && previous.some((p) => p.topic === job.topic && p.state === "running"),
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
    if (!topic.trim()) return;
    setSending(true);
    setFailed(false);
    try {
      await startDocumentary(projectName, topic.trim(), language);
      setTopic("");
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
        <span className="text-text-2">{t("documentary_label")}</span>
        <span className="flex gap-2">
          <input
            className="sa-input flex-1"
            placeholder={t("documentary_placeholder")}
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
          />
          <select
            className="sa-input w-auto"
            aria-label={t("documentary_language")}
            value={language}
            onChange={(event) => setLanguage(event.target.value as DocumentaryJob["language"])}
          >
            {LANGUAGES.map((code) => (
              <option key={code} value={code}>
                {t(`story_language_${code}`)}
              </option>
            ))}
          </select>
          <button type="submit" className="sa-btn" disabled={sending || !topic.trim()}>
            {t("documentary_create")}
          </button>
        </span>
      </label>
      <p className="mt-1.5 text-[11px] text-text-3">{t("documentary_hint")}</p>
      {jobs.map((job) => (
        <p key={job.topic} className="mt-1 text-text-2" role="status">
          {job.title ?? job.topic}: {t(`documentary_state_${job.state}`, { claims: job.claims })}
          {job.state === "failed" && job.error ? ` (${job.error})` : null}
        </p>
      ))}
      {failed ? (
        <p role="alert" className="mt-1 text-danger">
          {t("documentary_failed")}
        </p>
      ) : null}
    </form>
  );
}
