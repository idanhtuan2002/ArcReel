import { useCallback, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Bot } from "lucide-react";

import { useAppStore } from "@/stores/app-store";
import { controlProductionRun, getProductionRun, newCommandId } from "@/features/production-run/api/productionRunClient";
import { useAutopilotErrorText } from "./useAutopilotErrorText";
import {
  getAutopilot,
  setAutopilot,
  type AutopilotChange,
  type AutopilotStateName,
  type AutopilotView,
} from "./autopilotClient";

const POLL_MS = 30_000;
const CHAPTERS = { min: 6, max: 120 };

const TONE: Record<AutopilotStateName, string> = {
  off: "text-text-3",
  waiting: "text-accent",
  ready: "text-accent",
  halted: "text-warn",
  finished: "text-text-2",
};

/**
 * Story parameters a story project's autopilot writes from; ``null`` while they are invalid. An empty idea is left
 * out and the first part draws its own idea and, without a length, its length too (ADR-0125); a given idea needs its
 * length.
 */
export function storyAutopilot(idea: string, chapters: number | null, direction: string) {
  const text = idea.trim();
  if (chapters === null ? Boolean(text) : !Number.isInteger(chapters) || chapters < CHAPTERS.min || chapters > CHAPTERS.max) {
    return null;
  }
  return {
    ...(text ? { idea: text } : {}),
    ...(chapters !== null ? { book_chapters: chapters } : {}),
    ...(direction.trim() ? { direction: direction.trim() } : {}),
  };
}

export function StoryAutopilotFields({
  idea,
  onIdea,
  chapters,
  onChapters,
  direction,
  onDirection,
}: {
  idea: string;
  onIdea: (value: string) => void;
  chapters: number | null;
  onChapters: (value: number | null) => void;
  direction?: string;
  onDirection?: (value: string) => void;
}) {
  const { t } = useTranslation("dashboard");
  const ids = { idea: useId(), chapters: useId(), direction: useId() };
  const field =
    "mt-1 block w-full rounded-md border border-hairline-strong bg-transparent px-2.5 py-1.5 text-[13px] text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";
  return (
    <div className="space-y-2.5">
      <label htmlFor={ids.idea} className="block text-[12px] text-text-2">
        {t("ap_idea")}
        <textarea
          id={ids.idea}
          value={idea}
          onChange={(event) => onIdea(event.target.value)}
          rows={3}
          maxLength={4000}
          placeholder={t("ap_idea_auto")}
          className={field}
        />
      </label>
      <label htmlFor={ids.chapters} className="block w-32 text-[12px] text-text-2">
        {t("ap_chapters")}
        <input
          id={ids.chapters}
          type="number"
          min={CHAPTERS.min}
          max={CHAPTERS.max}
          value={chapters ?? ""}
          placeholder={idea.trim() ? undefined : t("ap_chapters_auto")}
          required={Boolean(idea.trim())}
          onChange={(event) => onChapters(event.target.value === "" ? null : Number(event.target.value))}
          className={field}
        />
      </label>
      {onDirection ? (
        <label htmlFor={ids.direction} className="block text-[12px] text-text-2">
          {t("ap_direction")}
          <input
            id={ids.direction}
            value={direction ?? ""}
            onChange={(event) => onDirection(event.target.value)}
            maxLength={4000}
            className={field}
          />
        </label>
      ) : null}
    </div>
  );
}

/**
 * ADR-0124: one line with the project's autopilot state and its switch. Turning a story project's autopilot on asks
 * for the idea and the book's length; a film project's for the episodes per run.
 */
export function AutopilotPanel({ projectName, kind }: { projectName: string; kind: "story" | "film" }) {
  const { t } = useTranslation("dashboard");
  const errorText = useAutopilotErrorText();
  const [view, setView] = useState<AutopilotView | null>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [idea, setIdea] = useState("");
  const [chapters, setChapters] = useState<number | null>(null);
  const [direction, setDirection] = useState("");
  const [episodes, setEpisodes] = useState(1);
  const episodesId = useId();

  const load = useCallback(
    (signal?: AbortSignal) =>
      getAutopilot(projectName, signal)
        .then((result) => setView(result?.status ? result : null))
        .catch(() => undefined),
    [projectName],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    const timer = window.setInterval(() => void load(controller.signal), POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [load]);

  const on = view?.delegation?.state === "ENABLED";
  const startEditing = () => {
    const previous = view?.delegation;
    if (previous?.story) {
      setIdea(previous.story.idea ?? "");
      setChapters(previous.story.book_chapters ?? null);
      setDirection(previous.story.direction ?? "");
    }
    if (previous?.film) setEpisodes(previous.film.episodes_per_run);
    setEditing(true);
  };

  const change = async (body: AutopilotChange) => {
    setBusy(true);
    try {
      const result = await setAutopilot(projectName, body);
      setView(result?.status ? result : null);
      setEditing(false);
    } catch (error) {
      useAppStore.getState().pushToast(`${t("ap_failed")}${errorText(error)}`, "error");
    } finally {
      setBusy(false);
    }
  };

  // A run that stopped for the Showrunner resumes here: a story project's page shows no run panel.
  const resume = async (runId: string) => {
    setBusy(true);
    try {
      const run = await getProductionRun(projectName, runId);
      await controlProductionRun(projectName, runId, "resume", {
        command_id: newCommandId(),
        expected_version: run.version,
        expected_input_digest: run.input_digest,
        policy_digest: run.policy_digest,
      });
      await load();
    } catch (error) {
      useAppStore.getState().pushToast(`${t("ap_failed")}${errorText(error)}`, "error");
    } finally {
      setBusy(false);
    }
  };

  const story = storyAutopilot(idea, chapters, direction);
  const episodesValid = Number.isInteger(episodes) && episodes >= 1 && episodes <= 12;
  const state = view?.status.state ?? "off";
  const haltedRun = state === "halted" ? (view?.status.run_id ?? null) : null;

  return (
    <section aria-labelledby={`${episodesId}-title`} className="rounded-md border border-hairline px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <h2 id={`${episodesId}-title`} className="flex items-center gap-1.5 text-[13px] font-medium text-text">
          <Bot aria-hidden className="h-4 w-4 text-text-3" />
          {t("ap_title")}
        </h2>
        {view ? (
          <span className={`text-[12px] ${TONE[state]}`} aria-live="polite">
            {t(`ap_state_${state}`)}
            {state === "halted" && view.status.reason ? (
              <span className="text-text-3"> · {t("ap_reason", { reason: view.status.reason })}</span>
            ) : null}
          </span>
        ) : null}
        {haltedRun ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => void resume(haltedRun)}
            className="rounded-md border border-accent/40 px-2.5 py-1 text-[12.5px] text-text hover:border-accent disabled:opacity-50"
          >
            {t("ap_resume")}
          </button>
        ) : null}
        <span className="ml-auto flex items-center gap-2">
          {view && !view.available ? <span className="text-[12px] text-text-3">{t("ap_unavailable")}</span> : null}
          {on ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void change({ enabled: false })}
              className="rounded-md border border-hairline px-2.5 py-1 text-[12.5px] text-text-2 hover:text-text disabled:opacity-50"
            >
              {t("ap_turn_off")}
            </button>
          ) : !editing ? (
            <button
              type="button"
              disabled={busy || !view?.available}
              onClick={startEditing}
              className="rounded-md border border-hairline px-2.5 py-1 text-[12.5px] text-text hover:border-accent/40 disabled:opacity-50"
            >
              {t("ap_turn_on")}
            </button>
          ) : null}
        </span>
      </div>
      {on && view?.delegation ? (
        <p className="mt-1 text-[12px] text-text-3">
          {view.delegation.story
            ? view.delegation.story.book_chapters
              ? t("ap_story_summary", { chapters: view.delegation.story.book_chapters })
              : t("ap_story_summary_auto")
            : t("ap_film_summary", { count: view.delegation.film?.episodes_per_run ?? 1 })}
        </p>
      ) : null}
      {editing && !on ? (
        <form
          className="mt-3 space-y-3 border-t border-hairline-soft pt-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (kind === "story" && story) void change({ enabled: true, story });
            if (kind === "film" && episodesValid) void change({ enabled: true, film: { episodes_per_run: episodes } });
          }}
        >
          <p className="text-[12px] text-text-3">{t(kind === "story" ? "ap_story_hint" : "ap_film_hint")}</p>
          {kind === "story" ? (
            <StoryAutopilotFields
              idea={idea}
              onIdea={setIdea}
              chapters={chapters}
              onChapters={setChapters}
              direction={direction}
              onDirection={setDirection}
            />
          ) : (
            <label htmlFor={episodesId} className="block w-40 text-[12px] text-text-2">
              {t("ap_episodes_per_run")}
              <input
                id={episodesId}
                type="number"
                min={1}
                max={12}
                value={episodes}
                onChange={(event) => setEpisodes(Number(event.target.value))}
                className="mt-1 block w-full rounded-md border border-hairline-strong bg-transparent px-2.5 py-1.5 text-[13px] text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </label>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-md border border-hairline px-3 py-1.5 text-[12.5px] text-text-2 hover:text-text"
            >
              {t("common:cancel")}
            </button>
            <button
              type="submit"
              disabled={busy || (kind === "story" ? story === null : !episodesValid)}
              className="rounded-md bg-accent px-3 py-1.5 text-[12.5px] font-medium text-[oklch(0.14_0_0)] disabled:opacity-50"
            >
              {t("ap_turn_on")}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
