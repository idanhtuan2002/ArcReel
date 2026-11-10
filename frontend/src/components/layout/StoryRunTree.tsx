import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useSearch } from "wouter";
import { Bot, Plus } from "lucide-react";

import { getAutopilot, type AutopilotStateName } from "@/features/autopilot/autopilotClient";

import { listRuns, type RunSummary } from "@/features/story-authoring/api/storyClient";
import { STORY_RUNS_CHANGED } from "@/features/story-authoring/ui/StoryAuthoringPage";

const POLL_MS = 20_000;
const WORKING = new Set(["RUNNING", "APPROVING", "PARTIALLY_COMMITTED"]);

/**
 * ADR-0122: the project's stories as a branch of the workspace tree under "Write story", with "New story" on top,
 * so the story page itself keeps the whole width for the story it shows.
 */
export function StoryRunTree({ projectName }: { projectName: string }) {
  const { t } = useTranslation("dashboard");
  const [location, navigate] = useLocation();
  const search = useSearch();
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [autopilot, setAutopilotState] = useState<AutopilotStateName | null>(null);
  const params = new URLSearchParams(search);
  const onStory = location === "/story" || location.startsWith("/story/");
  const creating = onStory && params.get("new") === "1";
  const current = onStory && !creating ? (params.get("run") ?? runs?.[0]?.run_id ?? null) : null;

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const tick = () => {
      getAutopilot(projectName, controller.signal)
        .then((view) => setAutopilotState(view?.status?.state ?? null))
        .catch(() => undefined);
      listRuns(projectName, { signal: controller.signal })
        .then((found) => setRuns(found))
        .catch(() => undefined)
        .finally(() => {
          if (!controller.signal.aborted) timer = window.setTimeout(tick, POLL_MS);
        });
    };
    tick();
    const refresh = () => {
      window.clearTimeout(timer);
      tick();
    };
    window.addEventListener(STORY_RUNS_CHANGED, refresh);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
      window.removeEventListener(STORY_RUNS_CHANGED, refresh);
    };
  }, [projectName]);

  return (
    <ul className="mb-1 ml-[18px] space-y-px border-l border-hairline-soft pl-2" aria-label={t("story_tree_label")}>
      <li>
        <button
          type="button"
          onClick={() => navigate("/story?new=1")}
          aria-current={creating ? "page" : undefined}
          className={`flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[12.5px] focus-ring hover:bg-white/5 ${
            creating ? "bg-accent-dim text-text" : "text-accent-2"
          }`}
        >
          <Plus aria-hidden className="h-3.5 w-3.5 shrink-0" />
          {t("story_new")}
        </button>
      </li>
      {autopilot && autopilot !== "off" ? (
        <li>
          <button
            type="button"
            onClick={() => navigate("/story")}
            title={t(`ap_state_${autopilot}`)}
            className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[12px] text-text-2 focus-ring hover:bg-white/5"
          >
            <Bot aria-hidden className={`h-3.5 w-3.5 shrink-0 ${autopilot === "halted" ? "text-warn" : "text-accent"}`} />
            <span className="min-w-0 flex-1 truncate">
              {t("ap_title")} · {t(`ap_state_${autopilot}`)}
            </span>
          </button>
        </li>
      ) : null}
      {runs === null ? null : runs.length === 0 ? (
        <li className="px-1.5 py-1 text-[12px] text-text-4">{t("story_runs_empty")}</li>
      ) : (
        runs.map((run) => {
          const active = current === run.run_id;
          return (
            <li key={run.run_id}>
              <button
                type="button"
                onClick={() => navigate(`/story?run=${encodeURIComponent(run.run_id)}`)}
                aria-current={active ? "page" : undefined}
                title={run.idea}
                className={`flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[12.5px] focus-ring hover:bg-white/5 ${
                  active ? "bg-accent-dim text-text" : "text-text-2"
                }`}
              >
                <span
                  aria-hidden
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    WORKING.has(run.phase)
                      ? "bg-accent"
                      : run.phase.startsWith("BLOCKED") || run.phase === "MODEL_UNAVAILABLE" || run.phase === "COMMIT_BLOCKED"
                        ? "bg-warn"
                        : run.phase === "COMMITTED"
                          ? "bg-good"
                          : "bg-text-4"
                  }`}
                />
                <span className="min-w-0 flex-1 truncate">{run.idea}</span>
                <span className="sr-only">{t(`story_phase_${run.phase}`)}</span>
              </button>
            </li>
          );
        })
      )}
    </ul>
  );
}
