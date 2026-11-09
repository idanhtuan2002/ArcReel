import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { BookOpen, Clapperboard } from "lucide-react";

import { API } from "@/api";
import type { ProjectKind, ProjectSummary } from "@/types/project";

/**
 * ADR-0122: a new project is a story project (a standalone story, publishable on its own) or a film project, which
 * may adapt a story project; the film imports that story's text when it is created.
 */
export function ProjectKindPicker({
  kind,
  onKind,
  storyProject,
  onStoryProject,
}: {
  kind: ProjectKind;
  onKind: (kind: ProjectKind) => void;
  storyProject: string;
  onStoryProject: (name: string) => void;
}) {
  const { t } = useTranslation("dashboard");
  const id = useId();
  const [query, setQuery] = useState("");
  const [stories, setStories] = useState<ProjectSummary[]>([]);

  useEffect(() => {
    if (kind !== "film") return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      API.projectIndex({ kind: "story", q: query, sort: "title", limit: 100 }, controller.signal)
        .then((page) => setStories(page.items))
        .catch(() => undefined);
    }, 200);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [kind, query]);

  const option = (value: ProjectKind, Icon: typeof BookOpen) => (
    <label
      className={`flex flex-1 cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2.5 ${
        kind === value ? "border-accent/60 bg-accent-dim" : "border-hairline hover:border-hairline-strong"
      }`}
    >
      <input
        type="radio"
        name={`${id}-kind`}
        className="mt-1"
        checked={kind === value}
        onChange={() => onKind(value)}
      />
      <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-text-2" />
      <span>
        <span className="block text-[13.5px] text-text">{t(`new_project_kind_${value}`)}</span>
        <span className="block text-[12px] text-text-3">{t(`new_project_kind_${value}_hint`)}</span>
      </span>
    </label>
  );

  return (
    <fieldset className="mb-5 space-y-3">
      <legend className="mb-2 text-[12px] text-text-3">{t("new_project_kind")}</legend>
      <div className="flex flex-col gap-2 sm:flex-row">
        {option("story", BookOpen)}
        {option("film", Clapperboard)}
      </div>
      {kind === "film" ? (
        <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-text-2">
          <label htmlFor={`${id}-story`}>{t("new_project_story_source")}</label>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("new_project_story_search")}
            aria-label={t("new_project_story_search")}
            className="w-44 rounded-md border border-hairline-strong bg-transparent px-2 py-1 text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          />
          <select
            id={`${id}-story`}
            value={storyProject}
            onChange={(event) => onStoryProject(event.target.value)}
            className="min-w-0 max-w-full rounded-md border border-hairline-strong bg-transparent px-2 py-1 text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <option value="">{t("new_project_story_none")}</option>
            {storyProject && !stories.some((s) => s.name === storyProject) ? (
              <option value={storyProject}>{storyProject}</option>
            ) : null}
            {stories.map((story) => (
              <option key={story.name} value={story.name}>
                {story.title || story.name}
              </option>
            ))}
          </select>
        </div>
      ) : null}
    </fieldset>
  );
}
