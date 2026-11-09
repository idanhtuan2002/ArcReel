import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { SourcePreviewNote } from "./SourcePreviewNote";

/** Where an automatic run's story comes from (ADR-0115). */
export type StorySource = "idea" | "project" | "continue" | "variant";

export const STORY_SOURCES: StorySource[] = ["idea", "project", "continue", "variant"];

interface VariantProfile {
  id: string;
  label: string;
  instruction: string;
}

interface Props {
  projectName: string;
  source: StorySource;
  onSource: (source: StorySource) => void;
  sourceProject: string;
  onSourceProject: (name: string) => void;
  profile: string;
  onProfile: (id: string) => void;
  /** The choices offered; every source by default. */
  sources?: StorySource[];
}

const SELECT_CLS = "focus-ring rounded-md px-1.5 py-0.5";
const SELECT_STYLE = { border: "1px solid var(--color-hairline-strong)", background: "transparent" };

/**
 * Choose to write a new story, film the project's story, continue it, or write a variant of another project's story;
 * a variant names its source project and, optionally, a named variant profile.
 */
export function StorySourcePicker({
  projectName,
  source,
  onSource,
  sourceProject,
  onSourceProject,
  profile,
  onProfile,
  sources = STORY_SOURCES,
}: Props) {
  const { t } = useTranslation("workflow");
  const [projects, setProjects] = useState<{ name: string; title: string }[]>([]);
  const [profiles, setProfiles] = useState<VariantProfile[]>([]);

  // ADR-0122: the source is searched through the paged index, so any of thousands of projects can be found.
  const [query, setQuery] = useState("");
  useEffect(() => {
    if (source !== "variant") return;
    let live = true;
    const timer = window.setTimeout(() => {
      void API.projectIndex({ q: query, sort: "title", limit: 100 })
        .then((result) => {
          if (live) setProjects(result.items.filter((item) => item.name !== projectName));
        })
        .catch(() => undefined);
    }, 200);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [source, projectName, query]);

  useEffect(() => {
    if (source !== "variant") return;
    let live = true;
    void API.request<{ profiles: VariantProfile[] }>("/system/config/story-variant-profiles")
      .then((result) => {
        if (live) setProfiles(result.profiles);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [source, projectName]);

  return (
    <div className="space-y-1.5">
      <fieldset className="flex flex-wrap gap-3 text-[12px]" style={{ color: "var(--color-text-2)" }}>
        <legend className="sr-only">{t("auto_story_source")}</legend>
        {sources.map((value) => (
          <label key={value} className="flex items-center gap-1.5">
            <input type="radio" checked={source === value} onChange={() => onSource(value)} />
            {t(`auto_story_from_${value}`)}
          </label>
        ))}
      </fieldset>
      {source !== "idea" && (
        <p className="text-[12px]" style={{ color: "var(--color-text-3)" }}>
          {t(`auto_story_from_${source}_hint`)}
        </p>
      )}
      {(source === "project" || source === "continue") && <SourcePreviewNote projectName={projectName} />}
      {source === "variant" && (
        <div className="flex flex-wrap items-center gap-3 text-[12px]" style={{ color: "var(--color-text-2)" }}>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("auto_variant_source_search")}
            aria-label={t("auto_variant_source_search")}
            className={`${SELECT_CLS} w-40`}
            style={SELECT_STYLE}
          />
          <label className="flex items-center gap-1.5">
            {t("auto_variant_source_project")}
            <select
              className={SELECT_CLS}
              style={SELECT_STYLE}
              value={sourceProject}
              onChange={(event) => onSourceProject(event.target.value)}
            >
              <option value="">—</option>
              {sourceProject && !projects.some((item) => item.name === sourceProject) ? (
                <option value={sourceProject}>{sourceProject}</option>
              ) : null}
              {projects.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.title || item.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            {t("auto_variant_profile")}
            <select
              className={SELECT_CLS}
              style={SELECT_STYLE}
              value={profile}
              onChange={(event) => onProfile(event.target.value)}
            >
              <option value="">{t("auto_variant_profile_none")}</option>
              {profiles.map((item) => (
                <option key={item.id} value={item.id} title={item.instruction}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
    </div>
  );
}
