import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "wouter";

import { API } from "@/api";
import { listRuns, type RunSummary } from "@/features/story-authoring/api/storyClient";
import type { ProjectSummary } from "@/types/project";
import type { TaskItem } from "@/types/task";

import { summarizeOperations, type OperationsSummary } from "./operations-summary";
import "./operations-overview.css";

const POLL_MS = 30_000;

/** 运营总览的纯展示部分。 */
export function OperationsOverviewView({ summary }: { summary: OperationsSummary }) {
  const { t } = useTranslation("dashboard");
  return (
    <section aria-labelledby="ops-title" className="ops-overview">
      <div className="ops-head">
        <h2 id="ops-title">{t("ops_title")}</h2>
        <p>{t("ops_boundary")}</p>
      </div>
      <div className="ops-columns">
        <div>
          <h3>
            {t("pipeline_decisions_title")} <span className="ops-count">{summary.decisions.length}</span>
          </h3>
          {summary.decisions.length === 0 ? (
            <p className="ops-empty">{t("pipeline_nothing_waiting")}</p>
          ) : (
            <ul>
              {summary.decisions.map((item) => (
                <li key={item.runId}>
                  <Link href={`/app/projects/${encodeURIComponent(item.project)}/story`} className="ops-link">
                    {t("ops_decision_story", { project: item.title, idea: item.idea.slice(0, 70) })}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3>
            {t("pipeline_running_title")} <span className="ops-count">{summary.running.length}</span>
          </h3>
          {summary.running.length === 0 ? (
            <p className="ops-empty">{t("ops_nothing_running")}</p>
          ) : (
            <ul>
              {summary.running.map((item) => (
                <li key={item.project}>
                  <Link href={`/app/projects/${encodeURIComponent(item.project)}`} className="ops-link">
                    {t("ops_running_project", { project: item.title, stories: item.storyRuns, tasks: item.tasks })}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3>{t("ops_stages_title")}</h3>
          <ul>
            {summary.stages.map((item) => (
              <li key={item.project} className="ops-stage">
                <Link href={`/app/projects/${encodeURIComponent(item.project)}`} className="ops-link">
                  {item.title}
                </Link>
                <span>{item.stage ? t(`pipeline_stage_${item.stage}`) : t("ops_stage_unknown")}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

/** 容器：读取各项目的故事运行与全局进行中任务，定时刷新。 */
export function OperationsOverview({ projects }: { projects: ProjectSummary[] }) {
  const [runsByProject, setRunsByProject] = useState<Record<string, RunSummary[]>>({});
  const [activeTasks, setActiveTasks] = useState<TaskItem[]>([]);
  const names = projects.map((project) => project.name).join("\n");

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async () => {
      const list = names ? names.split("\n") : [];
      const settled = await Promise.allSettled(list.map((name) => listRuns(name, { signal: controller.signal })));
      const [running, queued] = await Promise.allSettled([
        API.listTasks({ status: "running", pageSize: 200 }),
        API.listTasks({ status: "queued", pageSize: 200 }),
      ]);
      if (controller.signal.aborted) return;
      setRunsByProject(
        Object.fromEntries(list.map((name, index) => [name, settled[index].status === "fulfilled" ? settled[index].value : []])),
      );
      setActiveTasks([
        ...(running.status === "fulfilled" ? running.value.items : []),
        ...(queued.status === "fulfilled" ? queued.value.items : []),
      ]);
      timer = window.setTimeout(() => void load(), POLL_MS);
    };
    void load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [names]);

  if (projects.length === 0) return null;
  return <OperationsOverviewView summary={summarizeOperations(projects, runsByProject, activeTasks)} />;
}
