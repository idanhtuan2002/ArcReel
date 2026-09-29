/**
 * One node view for every Canvas node type. Below the LOD zoom threshold a node
 * shows only its type kicker and title: no text fields, images or video.
 */
import { memo, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { Handle, Position, useStore, type NodeProps, type ReactFlowState } from "@xyflow/react";
import { useShallow } from "zustand/react/shallow";

import { API } from "@/api";

import { isStoryboardGroupNode } from "../domain/geometry";
import { commitEdit } from "../domain/graph";
import type { CanvasNode } from "../domain/types";
import { useCanvasStore } from "../state/canvasStore";
import { useCanvasProject } from "./canvasContext";

/** Below this zoom a node renders as a compact card (the LOD step of the benchmark protocol). */
export const LOD_ZOOM = 0.35;

const lowDetail = (state: ReactFlowState) => state.transform[2] < LOD_ZOOM;

const KICKERS: Record<string, string> = {
  beat: "BEAT",
  note: "NOTE",
  frame: "FRAME",
  clip: "CLIP",
  audio: "AUDIO",
  group: "GROUP",
};

const ACCENTS: Record<string, string> = {
  beat: "text-warm",
  note: "text-text-3",
  frame: "text-accent",
  clip: "text-accent-2",
  audio: "text-good",
  group: "text-text-3",
};

function stringData(node: Pick<CanvasNode, "data">, key: string): string {
  const value = node.data[key];
  return typeof value === "string" ? value : "";
}

function updateNodeData(id: string, patch: Record<string, unknown>): void {
  useCanvasStore.getState().edit((graph) => {
    const target = graph.nodes.find((node) => node.id === id);
    if (!target || Object.entries(patch).every(([key, value]) => target.data[key] === value)) return graph;
    return commitEdit(
      graph,
      graph.nodes.map((node) => (node.id === id ? { ...node, data: { ...node.data, ...patch } } : node)),
      graph.edges,
    );
  });
}

/** A field edited locally and committed as one edit when it loses focus. */
function CommitField({
  nodeId,
  field,
  value,
  label,
  multiline,
}: {
  nodeId: string;
  field: string;
  value: string;
  label: string;
  multiline?: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? value;
  const commit = () => {
    if (draft !== null) updateNodeData(nodeId, { [field]: draft });
    setDraft(null);
  };
  const onKeyDown = (event: KeyboardEvent) => {
    event.stopPropagation();
    if (event.key === "Escape") setDraft(null);
    if (event.key === "Enter" && !multiline) (event.target as HTMLElement).blur();
  };
  const className =
    "nodrag nowheel w-full resize-none rounded-md border border-hairline-soft bg-bg/60 px-2 py-1 text-sm text-text placeholder:text-text-4 focus:border-accent focus:outline-none";
  return multiline ? (
    <textarea
      aria-label={label}
      className={`${className} min-h-24`}
      value={shown}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={onKeyDown}
    />
  ) : (
    <input
      aria-label={label}
      className={`${className} font-medium`}
      value={shown}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={onKeyDown}
    />
  );
}

function MediaStill({ path, alt }: { path: string; alt: string }) {
  const project = useCanvasProject();
  return (
    <img
      src={API.getFileUrl(project, path)}
      alt={alt}
      loading="lazy"
      decoding="async"
      draggable={false}
      className="aspect-video w-full rounded-md bg-surface-2 object-cover"
    />
  );
}

function ClipMedia({ node, title }: { node: NodeProps["data"] & object; title: string }) {
  const { t } = useTranslation("dashboard");
  const project = useCanvasProject();
  const [playing, setPlaying] = useState(false);
  const clip = typeof node.assetRef === "string" ? node.assetRef : "";
  const still = typeof node.thumbnailRef === "string" ? node.thumbnailRef : "";
  if (playing && clip) {
    return (
      <video
        src={API.getFileUrl(project, clip)}
        controls
        autoPlay
        muted
        className="nodrag aspect-video w-full rounded-md bg-black"
        aria-label={title}
      />
    );
  }
  return (
    <button
      type="button"
      className="nodrag group relative block w-full rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
      onClick={() => setPlaying(true)}
      aria-label={`${t("creative_canvas_play_clip")}: ${title}`}
    >
      {still ? <MediaStill path={still} alt="" /> : <span className="block aspect-video w-full rounded-md bg-surface-2" />}
      <span className="absolute inset-0 grid place-items-center text-2xl text-text/80 group-hover:text-text" aria-hidden>
        ▶
      </span>
    </button>
  );
}

function StoryboardBoard({ id }: { id: string }) {
  const members = useCanvasStore(useShallow((state) => state.graph.nodes.filter((node) => node.parentId === id)));
  return (
    <div className="pointer-events-none absolute inset-0">
      {members.map((member) => {
        const path = stringData(member, "assetRef");
        const style = { left: member.position.x, top: member.position.y, width: member.style?.width ?? member.width };
        return path ? (
          <div key={member.id} className="absolute" style={style}>
            <MediaStill path={path} alt="" />
          </div>
        ) : null;
      })}
    </div>
  );
}

function CanvasNodeViewImpl({ id, type, data, selected }: NodeProps) {
  const { t } = useTranslation("dashboard");
  const compact = useStore(lowDetail);
  const project = useCanvasProject();
  const node = { data: data };
  const title = stringData(node, "label") || stringData(node, "displayName") || t("creative_canvas_untitled");
  const storyboard = type === "group" && isStoryboardGroupNode({ id, type: "group", position: { x: 0, y: 0 }, data: node.data });
  const kicker = storyboard ? "STORYBOARD" : (KICKERS[type] ?? type.toUpperCase());

  if (type === "group") {
    return (
      <div
        className={`canvas-group relative h-full w-full rounded-xl border border-dashed ${
          selected ? "border-accent" : "border-hairline-strong"
        } ${storyboard ? "bg-warm-tint-faint" : "bg-surface-2/20"}`}
      >
        <div className={`${storyboard ? "storyboard-handle cursor-grab" : ""} flex items-center gap-2 px-3 py-2`}>
          <span className={`font-mono text-[10px] tracking-[0.18em] ${storyboard ? "text-warm" : "text-text-3"}`}>{kicker}</span>
          <span className="truncate text-xs text-text-2">{title}</span>
        </div>
        {storyboard && !compact ? <StoryboardBoard id={id} /> : null}
      </div>
    );
  }

  const text = type === "beat" || type === "note";
  const assetRef = stringData(node, "assetRef");
  return (
    <div
      className={`canvas-node flex h-full w-full flex-col gap-2 rounded-xl border bg-bg-grad-a p-3 ${
        selected ? "border-accent shadow-glow" : "border-hairline"
      }`}
    >
      <Handle type="target" position={Position.Left} className="canvas-handle" />
      <span className={`font-mono text-[10px] tracking-[0.18em] ${ACCENTS[type] ?? "text-text-3"}`}>{kicker}</span>
      {compact || !text ? (
        <p className="truncate text-sm font-medium text-text">{title}</p>
      ) : (
        <CommitField nodeId={id} field="label" value={stringData(node, "label")} label={t("creative_canvas_label_field")} />
      )}
      {compact ? null : text ? (
        <CommitField nodeId={id} field="text" value={stringData(node, "text")} label={t("creative_canvas_text_field")} multiline />
      ) : type === "clip" ? (
        <ClipMedia node={node.data} title={title} />
      ) : assetRef && type === "frame" ? (
        <MediaStill path={assetRef} alt={title} />
      ) : assetRef && type === "audio" ? (
        // eslint-disable-next-line jsx-a11y/media-has-caption -- a referenced project audio file has no caption source
        <audio className="nodrag w-full" controls preload="none" src={API.getFileUrl(project, assetRef)} aria-label={title} />
      ) : null}
      <Handle type="source" position={Position.Right} className="canvas-handle" />
    </div>
  );
}

export const CanvasNodeView = memo(CanvasNodeViewImpl);
