import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "wouter";
import { AlertTriangle, BookOpen, ChevronDown, ChevronRight, Clapperboard, Hand, Loader2 } from "lucide-react";

import { API } from "@/api";
import type { OperationsItem, OperationsLane, OperationsOverviewData } from "@/types/project";

const POLL_MS = 30_000;
const SHOWN = 5;
const COLLAPSE_KEY = "arcreel.controlRoom.opsCollapsed";
const LANES: OperationsLane[] = ["decision", "blocked", "running"];
const LANE_ICON = { decision: Hand, blocked: AlertTriangle, running: Loader2 } as const;

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeCollapsed(value: boolean) {
  try {
    window.localStorage.setItem(COLLAPSE_KEY, value ? "1" : "0");
  } catch {
    /* a private window keeps the choice for this page only */
  }
}

/** Where an item is acted on: a story run on the story page, a production run in the project. */
export function itemHref(item: OperationsItem): string {
  const base = `/app/projects/${encodeURIComponent(item.project)}`;
  return item.kind === "story_run" ? `${base}/story` : base;
}

function Lane({ lane, items, total }: { lane: OperationsLane; items: OperationsItem[]; total: number }) {
  const { t } = useTranslation("dashboard");
  const [all, setAll] = useState(false);
  const Icon = LANE_ICON[lane];
  const shown = all ? items : items.slice(0, SHOWN);
  return (
    <div className="min-w-0" data-lane={lane}>
      <h3 className="mb-1.5 flex items-center gap-1.5 text-[12px] font-medium text-text-2">
        <Icon
          aria-hidden
          className={`h-3.5 w-3.5 ${lane === "blocked" ? "text-warn" : lane === "decision" ? "text-accent" : "text-text-3"}`}
        />
        {t(`cr_lane_${lane}`)}
        <span className="tabular-nums text-text-3">{total}</span>
      </h3>
      {items.length === 0 ? (
        <p className="text-[12px] text-text-3">{t(`cr_lane_${lane}_empty`)}</p>
      ) : (
        <ul className="space-y-0.5">
          {shown.map((item) => (
            <li key={`${item.kind}-${item.run_id}`}>
              <Link
                href={itemHref(item)}
                className="group flex items-center gap-2 rounded px-1.5 py-1 text-[12.5px] text-text hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                {item.project_kind === "story" ? (
                  <BookOpen aria-hidden className="h-3.5 w-3.5 shrink-0 text-text-3" />
                ) : (
                  <Clapperboard aria-hidden className="h-3.5 w-3.5 shrink-0 text-text-3" />
                )}
                <span className="min-w-0 flex-1 truncate">{item.title}</span>
                <span className="shrink-0 text-[11px] text-text-3">
                  {t(item.kind === "story_run" ? "cr_kind_story_run" : "cr_kind_production_run")} ·{" "}
                  {t(`cr_state_${item.state}`, { defaultValue: item.state })}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {items.length > SHOWN ? (
        <button
          type="button"
          className="mt-1 px-1.5 text-[12px] text-text-3 hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          onClick={() => setAll((value) => !value)}
        >
          {all ? t("cr_show_less") : t("cr_show_more", { count: items.length - SHOWN })}
        </button>
      ) : null}
    </div>
  );
}

/**
 * ADR-0122: what needs the operator across every project — decisions, stops and running work — in one strip that
 * collapses to a line of counts. Read-only: each item links to the place where it is acted on.
 */
export function OperationsStrip() {
  const { t } = useTranslation("dashboard");
  const [data, setData] = useState<OperationsOverviewData | null>(null);
  const [failed, setFailed] = useState(false);
  const [collapsed, setCollapsed] = useState(readCollapsed);

  useEffect(() => {
    const controller = new AbortController();
    const tick = () =>
      API.operations(controller.signal)
        .then((result) => {
          setData(result);
          setFailed(false);
        })
        .catch(() => {
          if (!controller.signal.aborted) setFailed(true);
        });
    void tick();
    const timer = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  const toggle = () => {
    setCollapsed((value) => {
      writeCollapsed(!value);
      return !value;
    });
  };

  const counts = data?.counts;
  const quiet = counts !== undefined && counts.decision + counts.blocked + counts.running + counts.tasks === 0;
  return (
    <section aria-labelledby="cr-ops-title" className="border-b border-hairline px-6 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <button
          type="button"
          onClick={toggle}
          aria-expanded={!collapsed}
          aria-controls={!collapsed && data && !quiet ? "cr-ops-lanes" : undefined}
          className="flex items-center gap-1.5 text-[13px] font-medium text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          {collapsed ? <ChevronRight aria-hidden className="h-4 w-4" /> : <ChevronDown aria-hidden className="h-4 w-4" />}
          <span id="cr-ops-title">{t("cr_ops_title")}</span>
        </button>
        {counts ? (
          <p className="flex flex-wrap gap-x-3 text-[12px] text-text-3" aria-live="polite">
            {quiet ? (
              <span>{t("cr_ops_quiet")}</span>
            ) : (
              <>
                <span className={counts.decision ? "text-accent" : undefined}>
                  {t("cr_count_decision", { count: counts.decision })}
                </span>
                <span className={counts.blocked ? "text-warn" : undefined}>
                  {t("cr_count_blocked", { count: counts.blocked })}
                </span>
                <span>{t("cr_count_running", { count: counts.running })}</span>
                <span>{t("cr_count_tasks", { count: counts.tasks })}</span>
              </>
            )}
          </p>
        ) : failed ? (
          <p className="text-[12px] text-text-3">{t("cr_ops_failed")}</p>
        ) : null}
      </div>
      {!collapsed && data && !quiet ? (
        <div id="cr-ops-lanes" className="mt-3 grid gap-6 md:grid-cols-3">
          {LANES.map((lane) => (
            <Lane key={lane} lane={lane} items={data.lanes[lane] ?? []} total={data.counts[lane]} />
          ))}
        </div>
      ) : null}
    </section>
  );
}
