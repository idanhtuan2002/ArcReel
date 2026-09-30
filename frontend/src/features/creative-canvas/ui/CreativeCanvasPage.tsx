/**
 * The Creative Canvas of one episode (route `episodes/:episodeId/canvas`).
 * Loaded lazily, so React Flow stays out of the initial bundle.
 */
import "@xyflow/react/dist/base.css";
import "./canvas.css";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "wouter";
import { ReactFlowProvider, useReactFlow } from "@xyflow/react";
import {
  ArrowLeft,
  BoxSelect,
  Clapperboard,
  Film,
  Maximize,
  Redo2,
  Save,
  StickyNote,
  Undo2,
  Ungroup,
  Zap,
} from "lucide-react";

import i18n from "@/i18n";
import { WORKSPACE_ROUTE_EPISODES } from "@/app-routes";
import { useProjectsStore } from "@/stores/projects-store";
import type { EditorContentMode } from "@/utils/script-shape";

import { canvasCandidateId } from "../api/explorationClient";
import { digitToBookmarkIndex } from "../domain/bookmarks";
import { isGroupNode } from "../domain/geometry";
import { addNode, redo, undo } from "../domain/graph";
import { groupNodes, mergeStoryboardGroup, ungroupNode, type GroupDeps } from "../domain/groups";
import { useCanvasStore } from "../state/canvasStore";
import { canvasSaveScope, useSaveState } from "../state/saveStatusStore";
import { hasUnstoredKeptAside } from "../recovery/keptAside";
import { CanvasPersistence, defaultPersistenceDeps } from "../sync/canvasPersistence";
import { CanvasBoard } from "./CanvasBoard";
import { CanvasProjectContext } from "./canvasContext";
import { ConflictBanner } from "./ConflictBanner";
import { createTextNode, episodeShots, importEpisodeShots, type TextNodeType } from "./nodeFactory";
import { selectOnly } from "./selection";
import { StoryboardFilmstrip } from "./StoryboardFilmstrip";

interface CreativeCanvasPageProps {
  projectName: string;
  episode: number;
}

const translate = (key: string, params?: Record<string, unknown>) => i18n.t(key, { ns: "dashboard", ...params });
const newId = () => crypto.randomUUID();

function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

const conflictIds = new WeakMap<object, number>();
let lastConflictId = 0;

/** A stable id per shown conflict object. */
function conflictIdentity(conflict: object | null): number {
  if (!conflict) return 0;
  let id = conflictIds.get(conflict);
  if (id === undefined) {
    lastConflictId += 1;
    id = lastConflictId;
    conflictIds.set(conflict, id);
  }
  return id;
}

function contentMode(value: unknown): EditorContentMode {
  return value === "drama" || value === "ad" ? value : "narration";
}

function SaveChip({ scope }: { scope: string }) {
  const { t } = useTranslation("dashboard");
  const state = useSaveState(scope);
  const tone =
    state.status === "error" ? "text-danger-2" : state.status === "saving" ? "text-accent-2" : "text-text-3";
  const text = {
    idle: t("creative_canvas_status_idle"),
    saving: t("creative_canvas_status_saving"),
    saved: t("creative_canvas_status_saved"),
    error: t("creative_canvas_status_error"),
  }[state.status];
  return (
    <p role="status" className={`font-mono text-[11px] ${tone}`} title={state.error}>
      <span aria-hidden className="cc-dot mr-1.5 inline-block rounded-full align-middle" />
      {text}
      {state.status === "error" && state.error ? <span className="sr-only">: {state.error}</span> : null}
    </p>
  );
}

function ToolButton({
  label,
  icon: Icon,
  onClick,
  disabled,
}: {
  label: string;
  icon: typeof Save;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-text-2 cc-tool hover:text-text disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
    >
      <Icon aria-hidden className="cc-icon" />
      {label}
    </button>
  );
}

function CanvasWorkspace({ projectName, episode }: CreativeCanvasPageProps) {
  const { t } = useTranslation("dashboard");
  const flow = useReactFlow();
  const [persistence] = useState(() => new CanvasPersistence(defaultPersistenceDeps(translate)));
  const phase = useCanvasStore((state) => state.phase);
  const loadError = useCanvasStore((state) => state.loadError);
  const hasConflict = useCanvasStore((state) => state.conflict !== null);
  // One banner per kept-aside version: a confirmation started for one never carries to the next.
  const conflictKey = useCanvasStore((state) => conflictIdentity(state.conflict));
  const conflictMode = useCanvasStore((state) => state.conflictMode);
  const empty = useCanvasStore((state) => state.graph.nodes.length === 0);
  const canUndo = useCanvasStore((state) => state.graph.history.past.length > 0);
  const canRedo = useCanvasStore((state) => state.graph.history.future.length > 0);
  const selectedIds = useCanvasStore((state) => state.graph.nodes.filter((node) => node.selected).map((node) => node.id).join(","));
  const edit = useCanvasStore((state) => state.edit);
  const project = useProjectsStore((state) => state.currentProjectData);
  const scripts = useProjectsStore((state) => state.currentScripts);
  const [notice, setNotice] = useState("");

  const episodeEntry = project?.episodes?.find((item) => item.episode === episode);
  const scriptFile = episodeEntry?.script_file?.replace(/^scripts\//, "");
  const shots = useMemo(
    () => episodeShots(scriptFile ? scripts[scriptFile] : null, contentMode(project?.content_mode)),
    [scriptFile, scripts, project?.content_mode],
  );
  const saveScope = canvasSaveScope(projectName, canvasCandidateId(episode));

  useEffect(() => {
    void persistence.openCanvas(projectName, episode);
    return () => persistence.close();
  }, [persistence, projectName, episode]);

  // A version kept aside only in memory is lost when the tab closes: ask the browser to confirm.
  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (hasUnstoredKeptAside()) event.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

  const groupDeps = useMemo<GroupDeps>(
    () => ({
      newId,
      naming: {
        group: (index) => t("creative_canvas_group_name", { index }),
        storyboard: (index) => t("creative_canvas_storyboard_name", { index }),
        copy: (name) => t("creative_canvas_copy_name", { name }),
        frame: () => t("creative_canvas_frame_name"),
      },
    }),
    [t],
  );

  const viewCenter = useCallback(() => {
    const pane = document.querySelector(".canvas-shell")?.getBoundingClientRect();
    return pane
      ? flow.screenToFlowPosition({ x: pane.left + pane.width / 2, y: pane.top + pane.height / 2 })
      : { x: 0, y: 0 };
  }, [flow]);

  const addText = (type: TextNodeType) => {
    const center = viewCenter();
    const node = createTextNode(newId(), type, { x: center.x - 220, y: center.y - 160 });
    edit((graph) => selectOnly(addNode(graph, node), node.id));
  };

  const selection = selectedIds ? selectedIds.split(",") : [];
  const selectedGroup = useCanvasStore((state) =>
    state.graph.nodes.find((node) => node.selected && isGroupNode(node))?.id ?? null,
  );

  const onImport = () => {
    if (shots.length === 0) {
      setNotice(t("creative_canvas_import_empty"));
      return;
    }
    edit((graph) => importEpisodeShots(graph, shots, viewCenter(), groupDeps));
    requestAnimationFrame(() => void flow.fitView({ duration: 200 }));
  };

  const onShowShot = useCallback(
    (groupId: string) => {
      edit((graph) => selectOnly(graph, groupId));
      void flow.fitView({ nodes: [{ id: groupId }], duration: 200, maxZoom: 1 });
      requestAnimationFrame(() =>
        document.querySelector<HTMLElement>(`.react-flow__node[data-id="${CSS.escape(groupId)}"]`)?.focus(),
      );
    },
    [edit, flow],
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isTyping(event.target)) return;
      const mod = event.metaKey || event.ctrlKey;
      if (mod && event.key.toLowerCase() === "z") {
        event.preventDefault();
        edit((graph) => (event.shiftKey ? redo(graph) : undo(graph)).state);
      } else if (mod && event.key.toLowerCase() === "y") {
        event.preventDefault();
        edit((graph) => redo(graph).state);
      } else if (mod && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void persistence.saveNow();
      } else if (!mod && !event.altKey) {
        const slot = digitToBookmarkIndex(event.code.startsWith("Digit") ? event.code.slice(5) : "");
        if (slot === null) return;
        event.preventDefault();
        if (event.shiftKey) {
          const viewport = flow.getViewport();
          useCanvasStore.getState().editBookmarks((bookmarks) => bookmarks.map((item, index) => (index === slot ? viewport : item)));
          setNotice(t("creative_canvas_bookmark_saved", { slot: event.code.slice(5) }));
        } else {
          const bookmark = useCanvasStore.getState().bookmarks[slot];
          if (bookmark) void flow.setViewport(bookmark, { duration: 200 });
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [edit, flow, persistence, t]);

  const title = episodeEntry?.title;

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg">
      <header className="cc-header flex flex-wrap items-center border-b border-hairline py-2.5">
        <Link
          href={`/${WORKSPACE_ROUTE_EPISODES}/${episode}`}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-text-3 hover:text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        >
          <ArrowLeft aria-hidden className="cc-icon" />
          {t("creative_canvas_back")}
        </Link>
        <div className="min-w-0">
          <p className="font-mono text-[10px] tracking-[0.18em] text-text-3">
            EPISODE {String(episode).padStart(2, "0")} · CANVAS
          </p>
          <h1 className="truncate cc-title font-editorial leading-tight text-text">
            {title || t("creative_canvas_graph_label", { episode })}
          </h1>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <SaveChip scope={saveScope} />
          <button
            type="button"
            onClick={() => void persistence.saveNow()}
            disabled={phase !== "ready" || hasConflict}
            className="cc-btn-accent inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <Save aria-hidden className="cc-icon" />
            {t("creative_canvas_save")}
          </button>
        </div>
        <div role="toolbar" aria-label={t("creative_canvas_toolbar_label")} className="flex w-full flex-wrap items-center gap-1">
          <ToolButton label={t("creative_canvas_add_beat")} icon={Zap} onClick={() => addText("beat")} disabled={phase !== "ready" || hasConflict} />
          <ToolButton label={t("creative_canvas_add_note")} icon={StickyNote} onClick={() => addText("note")} disabled={phase !== "ready" || hasConflict} />
          <ToolButton label={t("creative_canvas_import_shots")} icon={Film} onClick={onImport} disabled={phase !== "ready" || hasConflict} />
          <span aria-hidden className="mx-1 h-4 w-px bg-hairline" />
          <ToolButton
            label={t("creative_canvas_group")}
            icon={BoxSelect}
            onClick={() => edit((graph) => groupNodes(graph, selection, groupDeps).state)}
            disabled={selection.length < 2 || hasConflict}
          />
          <ToolButton
            label={t("creative_canvas_make_storyboard")}
            icon={Clapperboard}
            onClick={() => edit((graph) => mergeStoryboardGroup(graph, selection, groupDeps).state)}
            disabled={selection.length < 2 || hasConflict}
          />
          <ToolButton
            label={t("creative_canvas_ungroup")}
            icon={Ungroup}
            onClick={() => selectedGroup && edit((graph) => ungroupNode(graph, selectedGroup).state)}
            disabled={!selectedGroup || hasConflict}
          />
          <span aria-hidden className="mx-1 h-4 w-px bg-hairline" />
          <ToolButton label={t("creative_canvas_undo")} icon={Undo2} onClick={() => edit((graph) => undo(graph).state)} disabled={!canUndo || hasConflict} />
          <ToolButton label={t("creative_canvas_redo")} icon={Redo2} onClick={() => edit((graph) => redo(graph).state)} disabled={!canRedo || hasConflict} />
          <ToolButton label={t("creative_canvas_fit")} icon={Maximize} onClick={() => void flow.fitView({ duration: 200 })} />
          <p aria-live="polite" className="ml-2 text-xs text-text-3">
            {notice}
          </p>
        </div>
      </header>
      {hasConflict ? (
        <ConflictBanner key={conflictKey} mode={conflictMode} onUseMine={() => void persistence.resolveConflict("mine")} onDiscardMine={() => void persistence.resolveConflict("server")} />
      ) : null}
      <div className="relative min-h-0 flex-1">
        {phase === "error" ? (
          <div role="alert" className="grid h-full place-items-center">
            <div className="text-center">
              <p className="text-sm text-text-2">{loadError ?? t("creative_canvas_load_failed")}</p>
              <button
                type="button"
                onClick={() => void persistence.openCanvas(projectName, episode)}
                className="mt-3 rounded-md border border-hairline-strong px-3 py-1.5 text-xs text-text-2 hover:text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              >
                {t("creative_canvas_retry")}
              </button>
            </div>
          </div>
        ) : phase === "ready" ? (
          <>
            <CanvasBoard label={t("creative_canvas_graph_label", { episode })} newId={newId} />
            {empty ? (
              <p className="pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2 text-center text-sm text-text-3">
                {t("creative_canvas_empty")}
              </p>
            ) : null}
          </>
        ) : (
          <p role="status" className="grid h-full place-items-center text-sm text-text-3">
            {t("creative_canvas_loading")}
          </p>
        )}
      </div>
      {phase === "ready" ? <StoryboardFilmstrip onShowShot={onShowShot} /> : null}
    </div>
  );
}

export default function CreativeCanvasPage(props: CreativeCanvasPageProps) {
  return (
    <CanvasProjectContext.Provider value={props.projectName}>
      <ReactFlowProvider>
        <CanvasWorkspace {...props} />
      </ReactFlowProvider>
    </CanvasProjectContext.Provider>
  );
}
