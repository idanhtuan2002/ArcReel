import type { Edge, Node } from "@xyflow/react";
import { STAGES, type RunSnapshot, type RunStage } from "../api/types";
import { formatDuration, type StageTime } from "./runTimeline";

export type StageState = "done" | "current" | "pending";

export interface StageNodeData extends Record<string, unknown> {
  kind: "stage";
  stage: RunStage;
  state: StageState;
  duration: string | null;
}

export interface TargetNodeData extends Record<string, unknown> {
  kind: "target";
  target: string;
  done: boolean;
}

export type RunGraphNode = Node<StageNodeData | TargetNodeData>;

export const STAGES_PER_ROW = 8;
const STEP_X = 150;
const STEP_Y = 110;

/**
 * The run as a read-only graph: the fixed stages in two rows (left to right, then right to left, so the flow reads
 * as one line), a loop edge for each repair the run made back to an earlier stage, and its target episodes after
 * EXPORT. Nothing here can be edited; the run's own stage order is the only graph.
 */
export function runGraph(
  run: RunSnapshot,
  times: Partial<Record<RunStage, StageTime>>,
): { nodes: RunGraphNode[]; edges: Edge[] } {
  const reached = STAGES.indexOf(run.stage);
  const finished = run.status === "SUCCEEDED";
  const position = (index: number) => {
    const row = Math.floor(index / STAGES_PER_ROW);
    const column = index % STAGES_PER_ROW;
    return { x: (row % 2 === 0 ? column : STAGES_PER_ROW - 1 - column) * STEP_X, y: row * STEP_Y };
  };
  const nodes: RunGraphNode[] = STAGES.map((stage, index) => {
    const time = times[stage];
    return {
      id: stage,
      type: "stage",
      position: position(index),
      data: {
        kind: "stage",
        stage,
        state: finished || index < reached ? "done" : index === reached ? "current" : "pending",
        duration: time ? formatDuration(time.ms) : null,
      },
    };
  });
  const edges: Edge[] = STAGES.slice(1).map((stage, index) => ({
    id: `${STAGES[index]}->${stage}`,
    source: STAGES[index],
    target: stage,
  }));
  // A repair goes back from the stage that judged the work to the stage that redoes it.
  for (const repair of run.repair_counts ?? []) {
    edges.push({
      id: `repair:${repair.stage}:${repair.unit_key}`,
      source: "QUALITY",
      target: repair.stage,
      label: `×${repair.count}`,
      data: { repair: true, unit: repair.unit_key },
      animated: false,
    });
  }
  const completed = new Set(run.completed_targets.map((output) => output.target));
  const last = position(STAGES.length - 1);
  run.targets.forEach((target, index) => {
    nodes.push({
      id: `target:${target}`,
      type: "target",
      position: { x: last.x - STEP_X * (index + 1), y: last.y + STEP_Y },
      data: { kind: "target", target, done: completed.has(target) },
    });
    edges.push({ id: `EXPORT->${target}`, source: "EXPORT", target: `target:${target}` });
  });
  return { nodes, edges };
}
