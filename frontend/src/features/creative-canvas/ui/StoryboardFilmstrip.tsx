/**
 * The storyboard order as a strip of film: one frame per shot, in the reading
 * order of each storyboard. It is also the linear, keyboard-first view of the
 * order: a listbox where arrow keys move between shots, Alt + arrow keys
 * reorder within a storyboard, and Enter shows the shot on the Canvas.
 */
import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { useShallow } from "zustand/react/shallow";

import { API } from "@/api";

import { isStoryboardGroupNode } from "../domain/geometry";
import { membersInReadingOrder, reorderStoryboardMember } from "../domain/groups";
import type { CanvasNode } from "../domain/types";
import { useCanvasStore } from "../state/canvasStore";
import { useCanvasProject } from "./canvasContext";

interface Shot {
  node: CanvasNode;
  groupId: string;
  indexInGroup: number;
}

interface StoryboardFilmstripProps {
  onShowShot: (groupId: string, nodeId: string) => void;
}

function shotName(node: CanvasNode, fallback: string): string {
  const label = node.data.label ?? node.data.displayName;
  return typeof label === "string" && label ? label : fallback;
}

export function StoryboardFilmstrip({ onShowShot }: StoryboardFilmstripProps) {
  const { t } = useTranslation("dashboard");
  const project = useCanvasProject();
  // Storyboard groups and their members only; other edits leave this list's items unchanged.
  const relevant = useCanvasStore(
    useShallow((state) => {
      const boards = new Set(state.graph.nodes.filter((node) => isStoryboardGroupNode(node)).map((node) => node.id));
      return state.graph.nodes.filter((node) => boards.has(node.id) || (node.parentId !== undefined && boards.has(node.parentId)));
    }),
  );
  const shots = useMemo<Shot[]>(
    () =>
      relevant
        .filter((node) => isStoryboardGroupNode(node))
        .flatMap((group) =>
          membersInReadingOrder(relevant, group.id).map((node, indexInGroup) => ({ node, groupId: group.id, indexInGroup })),
        ),
    [relevant],
  );
  const [active, setActive] = useState(0);
  const [announcement, setAnnouncement] = useState("");
  const listRef = useRef<HTMLUListElement>(null);
  const current = Math.min(active, Math.max(shots.length - 1, 0));

  const focusShot = (index: number) => {
    setActive(index);
    listRef.current?.querySelectorAll<HTMLElement>("[role=option]")[index]?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    const shot = shots[current];
    if (!shot) return;
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (step !== 0 && event.altKey) {
      event.preventDefault();
      const target = shot.indexInGroup + step;
      const groupSize = shots.filter((item) => item.groupId === shot.groupId).length;
      if (target < 0 || target >= groupSize) return;
      useCanvasStore.getState().edit((graph) => reorderStoryboardMember(graph, shot.groupId, shot.indexInGroup, target));
      setAnnouncement(
        t("creative_canvas_moved", { name: shotName(shot.node, t("creative_canvas_frame_name")), index: target + 1 }),
      );
      requestAnimationFrame(() => focusShot(current + step));
      return;
    }
    if (step !== 0) {
      event.preventDefault();
      focusShot(Math.min(Math.max(current + step, 0), shots.length - 1));
    } else if (event.key === "Home") {
      event.preventDefault();
      focusShot(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusShot(shots.length - 1);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onShowShot(shot.groupId, shot.node.id);
    }
  };

  return (
    <section className="filmstrip relative shrink-0 border-t border-hairline bg-bg-grad-b" aria-labelledby="canvas-filmstrip-title">
      <div className="flex items-baseline gap-3 px-4 pt-2">
        <h2 id="canvas-filmstrip-title" className="font-mono text-[10px] tracking-[0.18em] text-warm">
          STORYBOARD
          <span className="sr-only"> — {t("creative_canvas_filmstrip_label")}</span>
        </h2>
        <p id="canvas-filmstrip-hint" className="truncate text-[11px] text-text-3">
          {shots.length > 0 ? t("creative_canvas_filmstrip_hint") : t("creative_canvas_filmstrip_empty")}
        </p>
      </div>
      {shots.length > 0 ? (
        <ul
          ref={listRef}
          role="listbox"
          aria-label={t("creative_canvas_filmstrip_label")}
          aria-describedby="canvas-filmstrip-hint"
          aria-orientation="horizontal"
          onKeyDown={onKeyDown}
          className="filmstrip-track flex gap-2 overflow-x-auto px-4 pb-3 pt-2"
        >
          {shots.map((shot, index) => {
            const name = shotName(shot.node, t("creative_canvas_frame_name"));
            const path = typeof shot.node.data.assetRef === "string" ? shot.node.data.assetRef : "";
            return (
              // eslint-disable-next-line jsx-a11y/click-events-have-key-events -- the listbox handles arrow keys, Enter and Space for every option
              <li
                key={shot.node.id}
                role="option"
                aria-selected={index === current}
                aria-label={t("creative_canvas_shot", { index: index + 1, name })}
                tabIndex={index === current ? 0 : -1}
                onClick={() => {
                  setActive(index);
                  onShowShot(shot.groupId, shot.node.id);
                }}
                className="filmstrip-frame group relative w-28 shrink-0 cursor-pointer rounded-sm outline-none"
              >
                <span className="cc-frame-thumb block aspect-video overflow-hidden rounded-sm">
                  {path ? (
                    <img
                      src={API.getFileUrl(project, path)}
                      alt=""
                      width={112}
                      height={63}
                      loading="lazy"
                      decoding="async"
                      draggable={false}
                      className="h-full w-full object-cover"
                    />
                  ) : null}
                </span>
                <span className="mt-1 flex items-baseline gap-1.5 text-[11px]">
                  <span className="font-mono tabular-nums text-warm">{String(index + 1).padStart(2, "0")}</span>
                  <span className="truncate text-text-3">{name}</span>
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
    </section>
  );
}
