import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Clapperboard } from "lucide-react";

import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import type { ProjectSummary } from "@/types/project";
import { useAutopilotErrorText } from "./useAutopilotErrorText";
import { filmsForFinishedStories } from "./autopilotClient";

/**
 * ADR-0124 §6: make one film per finished story, each on autopilot, with the production settings of a film the
 * operator picks as the template. A rare action, so it folds into one button until opened.
 */
export function FilmsForStories({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation("dashboard");
  const errorText = useAutopilotErrorText();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [films, setFilms] = useState<ProjectSummary[]>([]);
  const [template, setTemplate] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    API.projectIndex({ kind: "film", sort: "updated", limit: 100 }, controller.signal)
      .then((page) => {
        setFilms(page.items);
        setTemplate((current) => current || page.items[0]?.name || "");
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [open]);

  const run = async () => {
    setBusy(true);
    try {
      const result = await filmsForFinishedStories(template);
      useAppStore
        .getState()
        .pushToast(t("ap_batch_done", { created: result.created.length, skipped: result.skipped.length }), "success");
      setOpen(false);
      onDone();
    } catch (error) {
      useAppStore.getState().pushToast(`${t("ap_batch_failed")}${errorText(error)}`, "error");
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-md border border-hairline px-2 py-0.5 text-[12px] text-text-2 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <Clapperboard aria-hidden className="h-3.5 w-3.5" />
        {t("ap_batch_open")}
      </button>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-hairline px-2 py-1 text-[12px] text-text-2">
      <label htmlFor={id}>{t("ap_batch_template")}</label>
      <select
        id={id}
        value={template}
        onChange={(event) => setTemplate(event.target.value)}
        className="max-w-[14rem] rounded-md border border-hairline-strong bg-transparent px-1.5 py-0.5 text-[12.5px] text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        {films.map((film) => (
          <option key={film.name} value={film.name}>
            {film.title || film.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        disabled={busy || !template}
        onClick={() => void run()}
        className="rounded-md bg-accent px-2.5 py-0.5 text-[12px] font-medium text-[oklch(0.14_0_0)] disabled:opacity-50"
      >
        {t("ap_batch_run")}
      </button>
      <button type="button" onClick={() => setOpen(false)} className="px-1 text-text-3 hover:text-text">
        {t("common:cancel")}
      </button>
    </div>
  );
}
