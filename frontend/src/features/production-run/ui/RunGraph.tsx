import "@xyflow/react/dist/base.css";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Handle, Position, ReactFlow, type NodeProps } from "@xyflow/react";
import type { RunSnapshot, RunStage } from "../api/types";
import { runGraph, type RunGraphNode, type StageNodeData, type TargetNodeData } from "./runGraph";
import type { StageTime } from "./runTimeline";

const HIDDEN_HANDLE = { opacity: 0, pointerEvents: "none" } as const;

function StageNode({ data }: NodeProps<RunGraphNode>) {
  const { t } = useTranslation("workflow");
  const stage = data as StageNodeData;
  const tone =
    stage.state === "current"
      ? "var(--color-accent-2)"
      : stage.state === "done"
        ? "var(--color-text-2)"
        : "var(--color-text-3)";
  return (
    <div
      className="rounded-md px-2 py-1 text-center text-[11px]"
      style={{
        width: 120,
        color: tone,
        border: `1px ${stage.state === "pending" ? "dashed" : "solid"} ${
          stage.state === "current" ? "var(--color-accent)" : "var(--color-hairline-strong)"
        }`,
        background: stage.state === "done" ? "var(--color-accent-dim)" : "var(--color-bg-1, transparent)",
      }}
    >
      <Handle type="target" position={Position.Left} style={HIDDEN_HANDLE} isConnectable={false} />
      <div>{t(`auto_stage_${stage.stage}`)}</div>
      {stage.duration && <div style={{ color: "var(--color-text-3)" }}>{stage.duration}</div>}
      <Handle type="source" position={Position.Right} style={HIDDEN_HANDLE} isConnectable={false} />
    </div>
  );
}

function TargetNode({ data }: NodeProps<RunGraphNode>) {
  const { t } = useTranslation("workflow");
  const target = data as TargetNodeData;
  return (
    <div
      className="rounded-full px-2 py-0.5 text-[11px]"
      style={{
        color: target.done ? "var(--color-accent-2)" : "var(--color-text-3)",
        border: `1px solid ${target.done ? "var(--color-accent)" : "var(--color-hairline-strong)"}`,
      }}
    >
      <Handle type="target" position={Position.Top} style={HIDDEN_HANDLE} isConnectable={false} />
      {t(target.done ? "auto_graph_target_done" : "auto_graph_target", {
        episode: Number(target.target.split(":")[1]),
      })}
    </div>
  );
}

const NODE_TYPES = { stage: StageNode, target: TargetNode };
const PRO_OPTIONS = { hideAttribution: true };

/** The run's stages, repair loops and episodes as a graph to look at; nothing on it can be moved or connected. */
export default function RunGraph({
  run,
  times,
}: {
  run: RunSnapshot;
  times: Partial<Record<RunStage, StageTime>>;
}) {
  const { t } = useTranslation("workflow");
  const { nodes, edges } = useMemo(() => runGraph(run, times), [run, times]);
  return (
    <div className="h-64 w-full rounded-md" style={{ border: "1px solid var(--color-hairline-strong)" }}>
      <ReactFlow
        aria-label={t("auto_graph")}
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        colorMode="dark"
        proOptions={PRO_OPTIONS}
        fitView
      />
    </div>
  );
}
