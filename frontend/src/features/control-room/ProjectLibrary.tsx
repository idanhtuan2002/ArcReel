import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation } from "wouter";
import { BookOpen, ChevronLeft, ChevronRight, Clapperboard, Trash2 } from "lucide-react";

import { API } from "@/api";
import { FilmsForStories } from "@/features/autopilot/FilmsForStories";
import { asProjectStatus, usePhaseLabels } from "@/components/pages/ProjectCard";
import { PHASE_ORDER, type Phase, type ProjectIndexPage, type ProjectIndexQuery, type ProjectSummary } from "@/types/project";

const PAGE = 50;
const KINDS = ["all", "story", "film"] as const;
type Kind = (typeof KINDS)[number];
type Sort = NonNullable<ProjectIndexQuery["sort"]>;

/** "3 phút trước" style relative time, in the reader's language. */
function useRelativeTime() {
  const { i18n } = useTranslation();
  return useMemo(() => {
    const format = new Intl.RelativeTimeFormat(i18n.language, { numeric: "auto" });
    return (iso: string | null | undefined) => {
      if (!iso) return "";
      const seconds = (new Date(iso).getTime() - Date.now()) / 1000;
      const steps: [Intl.RelativeTimeFormatUnit, number][] = [
        ["year", 31_536_000],
        ["month", 2_592_000],
        ["day", 86_400],
        ["hour", 3_600],
        ["minute", 60],
      ];
      for (const [unit, size] of steps) {
        if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
      }
      return format.format(Math.round(seconds), "second");
    };
  }, [i18n.language]);
}

function KindCell({ project }: { project: ProjectSummary }) {
  const { t } = useTranslation("dashboard");
  if (project.project_kind === "story") {
    return (
      <span className="inline-flex items-center gap-1.5 text-text-2">
        <BookOpen aria-hidden className="h-3.5 w-3.5" />
        {t("cr_kind_story")}
        {project.films ? <span className="text-text-3">· {t("cr_films", { count: project.films })}</span> : null}
      </span>
    );
  }
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-text-2">
      <Clapperboard aria-hidden className="h-3.5 w-3.5 shrink-0" />
      {t("cr_kind_film")}
      {project.story_project ? (
        <Link
          href={`/app/projects/${encodeURIComponent(project.story_project)}/story`}
          onClick={(event) => event.stopPropagation()}
          className="truncate text-text-3 underline-offset-2 hover:text-text hover:underline"
          title={t("cr_adapts", { project: project.story_project })}
        >
          ← {project.story_project}
        </Link>
      ) : null}
    </span>
  );
}

/**
 * ADR-0122: the project library as a dense, server-paged table — tabs per kind with counts, stage filter, sort,
 * pages of 50 — so thousands of story and film projects stay findable. A row opens its project.
 */
export function ProjectLibrary({
  search,
  reload,
  onDelete,
  onCreate,
}: {
  search: string;
  reload: number;
  onDelete: (project: ProjectSummary) => void;
  onCreate: () => void;
}) {
  const { t } = useTranslation("dashboard");
  const [, navigate] = useLocation();
  const phaseLabels = usePhaseLabels();
  const relative = useRelativeTime();
  const [kind, setKind] = useState<Kind>("all");
  const [stage, setStage] = useState<Phase | "">("");
  const [sort, setSort] = useState<Sort>("updated");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ProjectIndexPage | null>(null);
  const [failed, setFailed] = useState(false);
  const [query, setQuery] = useState(search);
  const [ownReload, setOwnReload] = useState(0);

  // Typing settles for a moment before the server is asked; a new query starts at the first page.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(search);
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    const controller = new AbortController();
    API.projectIndex({ q: query, kind, stage: stage || undefined, sort, offset, limit: PAGE }, controller.signal)
      .then((result) => {
        // A page emptied by a delete moves back to the last page that still has rows.
        if (result.items.length === 0 && result.total > 0 && offset > 0) {
          setOffset(Math.floor((result.total - 1) / PAGE) * PAGE);
          return;
        }
        setPage(result);
        setFailed(false);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [query, kind, stage, sort, offset, reload, ownReload]);

  const choose = <T,>(set: (value: T) => void) => (value: T) => {
    set(value);
    setOffset(0);
  };

  const counts = page?.counts;
  const total = page?.total ?? 0;
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + PAGE, total);

  return (
    <section aria-labelledby="cr-library-title" className="px-6 py-4">
      <h2 id="cr-library-title" className="sr-only">
        {t("cr_library_title")}
      </h2>
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <div role="tablist" aria-label={t("cr_library_title")} className="flex gap-1">
          {KINDS.map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={kind === value}
              onClick={() => choose(setKind)(value)}
              className={`rounded-md px-2.5 py-1 text-[13px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                kind === value ? "bg-accent-dim text-text" : "text-text-2 hover:text-text"
              }`}
            >
              {t(`cr_tab_${value}`)}
              {counts ? <span className="ml-1.5 tabular-nums text-text-3">{counts[value]}</span> : null}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1.5 text-[12px] text-text-3">
          {t("cr_filter_stage")}
          <select
            value={stage}
            onChange={(event) => choose(setStage)(event.target.value as Phase | "")}
            className="rounded-md border border-hairline-strong bg-transparent px-1.5 py-0.5 text-[12.5px] text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <option value="">{t("cr_filter_any")}</option>
            {PHASE_ORDER.map((phase) => (
              <option key={phase} value={phase}>
                {phaseLabels[phase]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-[12px] text-text-3">
          {t("cr_sort")}
          <select
            value={sort}
            onChange={(event) => choose(setSort)(event.target.value as Sort)}
            className="rounded-md border border-hairline-strong bg-transparent px-1.5 py-0.5 text-[12.5px] text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <option value="updated">{t("cr_sort_updated")}</option>
            <option value="title">{t("cr_sort_title")}</option>
            <option value="stage">{t("cr_sort_stage")}</option>
          </select>
        </label>
        {kind === "film" ? <FilmsForStories onDone={() => setOwnReload((value) => value + 1)} /> : null}
        <span className="ml-auto text-[12px] tabular-nums text-text-3">
          {t("cr_range", { first, last, total })}
        </span>
      </div>

      {failed ? (
        <p role="alert" className="py-8 text-center text-[13px] text-text-2">
          {t("cr_library_failed")}
        </p>
      ) : page && page.items.length === 0 ? (
        <div className="py-12 text-center text-[13px] text-text-2">
          <p>{query || stage || kind !== "all" ? t("cr_library_no_match") : t("cr_library_empty")}</p>
          {query || stage || kind !== "all" ? null : (
            <button type="button" onClick={onCreate} className="mt-3 rounded-md border border-hairline px-3 py-1.5 text-text hover:border-accent/40">
              {t("cr_create")}
            </button>
          )}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border border-hairline">
          <table className="w-full min-w-[720px] border-collapse text-left text-[13px]">
            <thead className="text-[11.5px] text-text-3">
              <tr className="border-b border-hairline">
                <th scope="col" className="px-3 py-2 font-medium">{t("cr_col_project")}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t("cr_col_kind")}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t("cr_col_stage")}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t("cr_col_episodes")}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t("cr_col_updated")}</th>
                <th scope="col" className="w-10 px-3 py-2"><span className="sr-only">{t("cr_col_actions")}</span></th>
              </tr>
            </thead>
            <tbody>
              {(page?.items ?? []).map((project) => {
                const status = asProjectStatus(project.status);
                const episodes = status?.episodes_summary;
                // A story project opens on its story; a film project on its overview.
                const href = `/app/projects/${encodeURIComponent(project.name)}${project.project_kind === "story" ? "/story" : ""}`;
                return (
                  <tr
                    key={project.name}
                    onClick={() => navigate(href)}
                    className="cursor-pointer border-b border-hairline-soft last:border-b-0 hover:bg-white/[0.03]"
                  >
                    <td className="max-w-0 px-3 py-2">
                      <Link
                        href={href}
                        onClick={(event) => event.stopPropagation()}
                        className="block truncate font-medium text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                      >
                        {project.title || project.name}
                      </Link>
                      {project.title && project.title !== project.name ? (
                        <span className="block truncate text-[11.5px] text-text-3">{project.name}</span>
                      ) : null}
                    </td>
                    <td className="max-w-[16rem] px-3 py-2">
                      <KindCell project={project} />
                    </td>
                    <td className="px-3 py-2 text-text-2">
                      {status ? phaseLabels[status.phase] : ""}
                      {status?.needs_repair ? <span className="ml-1.5 text-danger">{t("cr_needs_repair")}</span> : null}
                    </td>
                    <td className="px-3 py-2 tabular-nums text-text-2">
                      {episodes && episodes.total > 0 ? `${episodes.completed}/${episodes.total}` : "—"}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-text-3">{relative(project.updated_at)}</td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        aria-label={t("delete_project")}
                        title={t("delete_project")}
                        onClick={(event) => {
                          event.stopPropagation();
                          onDelete(project);
                        }}
                        className="rounded p-1 text-text-3 hover:bg-white/5 hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                      >
                        <Trash2 aria-hidden className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE ? (
        <nav aria-label={t("cr_pages")} className="mt-3 flex items-center justify-end gap-2 text-[12.5px]">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE))}
            className="inline-flex items-center gap-1 rounded-md border border-hairline px-2 py-1 text-text-2 enabled:hover:text-text disabled:opacity-40"
          >
            <ChevronLeft aria-hidden className="h-3.5 w-3.5" />
            {t("cr_prev")}
          </button>
          <button
            type="button"
            disabled={offset + PAGE >= total}
            onClick={() => setOffset(offset + PAGE)}
            className="inline-flex items-center gap-1 rounded-md border border-hairline px-2 py-1 text-text-2 enabled:hover:text-text disabled:opacity-40"
          >
            {t("cr_next")}
            <ChevronRight aria-hidden className="h-3.5 w-3.5" />
          </button>
        </nav>
      ) : null}
    </section>
  );
}
