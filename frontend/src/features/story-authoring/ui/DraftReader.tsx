import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { getDrafts, type StoryDrafts } from "../api/storyClient";

const POLL_MS = 15_000;

/** "scene_draft[2,3]" → the chapter and scene being written, numbered across a book from ``first``. */
function workingLabel(node: string, first: number, t: (key: string, values?: Record<string, unknown>) => string): string {
  const scene = /^scene_draft\[(\d+),(\d+)\]$/.exec(node);
  if (scene) return t("story_drafts_writing_scene", { chapter: first + Number(scene[1]) - 1, scene: Number(scene[2]) });
  const review = /^chapter_review\[(\d+)\]$/.exec(node);
  if (review) return t("story_drafts_reviewing", { chapter: first + Number(review[1]) - 1 });
  const plan = /^chapter_plan\[(\d+)\]$/.exec(node);
  if (plan) return t("story_drafts_planning", { chapter: first + Number(plan[1]) - 1 });
  return t("story_drafts_working_on", { node });
}

/**
 * What a story run has written so far, readable while it works (or after it stopped): each chapter's goal, the
 * scenes drafted, whether the chapter's review sealed it, and what is being generated now. A scene being generated
 * has no text until its call returns; drafts of an unsealed chapter may still be repaired.
 */
export function DraftReader({ projectName, runId, live }: { projectName: string; runId: string; live: boolean }) {
  const { t } = useTranslation("dashboard");
  const [drafts, setDrafts] = useState<StoryDrafts | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const tick = () => {
      getDrafts(projectName, runId, { signal: controller.signal })
        .then((result) => {
          if (Array.isArray(result?.chapters) && Array.isArray(result.working)) setDrafts(result);
          if (live) timer = window.setTimeout(tick, POLL_MS);
        })
        .catch(() => {
          if (!controller.signal.aborted && live) timer = window.setTimeout(tick, POLL_MS);
        });
    };
    tick();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [projectName, runId, live]);

  if (!drafts || drafts.chapters.length === 0) {
    return drafts && live ? (
      <section className="sa-panel rounded-md border border-hairline p-4 text-xs text-text-3">{t("story_drafts_none")}</section>
    ) : null;
  }
  const first = drafts.chapters[0]?.chapter ?? 1;
  const offset = first - 1;
  return (
    <section aria-labelledby="sa-drafts-title" className="sa-panel rounded-md border border-hairline p-4">
      <h3 id="sa-drafts-title" className="font-editorial text-base text-text">
        {t("story_drafts_title")}
      </h3>
      {drafts.working.length > 0 ? (
        <p className="mt-1 text-xs text-accent" role="status">
          {drafts.working.map((node) => workingLabel(node, offset + 1, t)).join(" · ")}
        </p>
      ) : null}
      <ol className="mt-3 space-y-2">
        {drafts.chapters.map((chapter) => {
          const expanded = open === chapter.chapter;
          return (
            <li key={chapter.chapter} className="rounded-md border border-hairline-soft">
              <button
                type="button"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : chapter.chapter)}
                className="flex w-full items-baseline gap-3 px-3 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <span className="shrink-0 text-[13px] font-medium text-text">
                  {t("story_drafts_chapter", { chapter: chapter.chapter })}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs text-text-2">{chapter.goal}</span>
                <span className="shrink-0 text-[11px] tabular-nums text-text-3">
                  {t("story_drafts_scenes", { done: chapter.scenes.length, planned: chapter.planned })}
                  {" · "}
                  {chapter.reviewed ? t("story_drafts_sealed") : t("story_drafts_unsealed")}
                </span>
              </button>
              {expanded ? (
                <div className="space-y-4 border-t border-hairline-soft px-3 py-3">
                  {chapter.scenes.map((scene) => (
                    <div key={scene.scene}>
                      <p className="mb-1 text-[11px] text-text-3">{t("story_drafts_scene", { scene: scene.scene })}</p>
                      <div className="max-w-[72ch] whitespace-pre-line text-[14px] leading-relaxed text-text">{scene.text}</div>
                    </div>
                  ))}
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
