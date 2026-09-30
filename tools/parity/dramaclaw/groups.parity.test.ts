/**
 * Donor side of the M8-B group, storyboard and sibling parity harness. Copied
 * into the pinned DramaClaw checkout by tools/parity/dramaclaw/run.sh; replays
 * the fixtures (PARITY_FIXTURES) on the unmodified donor store and writes
 * observations (PARITY_OUT) shaped like the port adapter
 * (frontend/src/features/creative-canvas/__parity__/groupsAdapter.ts).
 *
 * Donor-created ids are random; after every operation the ids that did not
 * exist before are renamed `n1`, `n2`, ... in array order, everywhere they
 * appear in the current nodes, edges and selection (never in history).
 */
import { readFileSync, writeFileSync } from "node:fs";
import { serialize } from "node:v8";

import { describe, expect, it } from "vitest";
import { timeCases } from "./timingRunner";

import { CANVAS_NODE_TYPES } from "@/features/canvas/domain/canvasNodes";
import { useCanvasStore, type CanvasEdge, type CanvasNode } from "@/stores/canvasStore";

const TO_DONOR: Record<string, string> = {
  beat: CANVAS_NODE_TYPES.textAnnotation,
  note: CANVAS_NODE_TYPES.textAnnotation,
  frame: CANVAS_NODE_TYPES.exportImage,
  clip: CANVAS_NODE_TYPES.video,
  audio: CANVAS_NODE_TYPES.audio,
  group: CANVAS_NODE_TYPES.group,
};
const TO_PORT: Record<string, string> = {
  [CANVAS_NODE_TYPES.textAnnotation]: "note",
  [CANVAS_NODE_TYPES.upload]: "frame",
  [CANVAS_NODE_TYPES.exportImage]: "frame",
  [CANVAS_NODE_TYPES.video]: "clip",
  [CANVAS_NODE_TYPES.audio]: "audio",
  [CANVAS_NODE_TYPES.group]: "group",
};
const STORYBOARD_KEYS = [
  "storyboardGroup",
  "storyboardAspect",
  "storyboardCols",
  "storyboardShowIndex",
  "storyboardBaseWidth",
  "storyboardBaseHeight",
];

interface FixtureNode {
  id: string;
  type: string;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
  parentId?: string;
}

type Op = { op: string; [key: string]: unknown };

const fixturesPath = process.env.PARITY_FIXTURES;
const outPath = process.env.PARITY_OUT;
const fixtures = fixturesPath
  ? (JSON.parse(readFileSync(fixturesPath, "utf-8")) as { fixture_set: string; cases: { id: string; ops: Op[] }[] })
  : { fixture_set: "none", cases: [] };

let portTypes = new Map<string, string>();
let known = new Set<string>();
let counter = 0;

function toDonorNode(item: FixtureNode): CanvasNode {
  portTypes.set(item.id, item.type);
  return {
    id: item.id,
    type: TO_DONOR[item.type],
    position: { x: item.x ?? 0, y: item.y ?? 0 },
    data: {},
    ...(item.w !== undefined ? { width: item.w } : {}),
    ...(item.h !== undefined ? { height: item.h } : {}),
    ...(item.parentId ? { parentId: item.parentId } : {}),
  } as unknown as CanvasNode;
}

/** Rename ids created by the last operation to n1, n2, ... everywhere in the current state. */
function renameCreatedIds(): void {
  const state = useCanvasStore.getState();
  const rename = new Map<string, string>();
  for (const node of state.nodes) {
    if (!known.has(node.id)) {
      counter += 1;
      rename.set(node.id, `n${counter}`);
    }
  }
  const swap = (value: string | undefined | null): string | undefined | null =>
    value && rename.has(value) ? rename.get(value) : value;
  const swapInId = (value: string): string => {
    let next = value;
    for (const [from, to] of rename) next = next.split(from).join(to);
    return next;
  };
  if (rename.size > 0) {
    useCanvasStore.setState({
      nodes: state.nodes.map((node) => ({
        ...node,
        id: swap(node.id) as string,
        ...(node.parentId ? { parentId: swap(node.parentId) as string } : {}),
      })),
      edges: state.edges.map((edge: CanvasEdge) => ({
        ...edge,
        id: swapInId(edge.id),
        source: swap(edge.source) as string,
        target: swap(edge.target) as string,
      })),
      selectedNodeId: swap(state.selectedNodeId) ?? null,
    });
  }
  for (const node of useCanvasStore.getState().nodes) {
    known.add(node.id);
    if (!portTypes.has(node.id)) portTypes.set(node.id, TO_PORT[node.type as string] ?? `donor:${node.type}`);
  }
}

function observe(op: string) {
  const state = useCanvasStore.getState();
  return {
    op,
    nodes: state.nodes.map((node) => {
      const data = node.data as Record<string, unknown>;
      const style = node.style as { width?: number; height?: number } | undefined;
      return {
        id: node.id,
        type: portTypes.get(node.id) ?? `donor:${node.type}`,
        parentId: node.parentId ?? null,
        x: node.position.x,
        y: node.position.y,
        width: node.width ?? null,
        height: node.height ?? null,
        styleWidth: style?.width ?? null,
        styleHeight: style?.height ?? null,
        hidden: node.hidden ?? false,
        selected: node.selected ?? false,
        dragHandle: node.dragHandle ?? null,
        storyboard: Object.fromEntries(STORYBOARD_KEYS.filter((key) => key in data).map((key) => [key, data[key]])),
      };
    }),
    edges: state.edges.map((edge) => {
      const data = (edge.data ?? {}) as Record<string, unknown>;
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        hidden: edge.hidden ?? false,
        origSource: (data.__sbOrigSource as string | undefined) ?? null,
        origTarget: (data.__sbOrigTarget as string | undefined) ?? null,
      };
    }),
    past: state.history.past.length,
    future: state.history.future.length,
    selected: state.selectedNodeId,
    edits: state.userEditsSinceHydrate,
  };
}

function apply(op: Op): void {
  const store = useCanvasStore.getState();
  switch (op.op) {
    case "load":
      store.setCanvasData(
        (op.nodes as FixtureNode[]).map(toDonorNode),
        (op.edges as { id: string; source: string; target: string }[]).map((edge) => ({ ...edge }) as CanvasEdge),
      );
      for (const item of op.nodes as FixtureNode[]) known.add(item.id);
      return;
    case "reload": {
      const current = useCanvasStore.getState();
      store.setCanvasData(current.nodes, current.edges);
      return;
    }
    case "select":
      store.setSelectedNode(op.id as string);
      return;
    case "undo":
      store.undo();
      return;
    case "redo":
      store.redo();
      return;
    case "group":
      store.groupNodes(op.ids as string[], { extraPadding: op.extraPadding as number | undefined });
      return;
    case "ungroup":
      store.ungroupNode(op.id as string);
      return;
    case "fit":
      store.fitGroupToChildren(op.id as string);
      return;
    case "arrange":
      store.arrangeGroupChildren(op.id as string, op.mode as never);
      return;
    case "merge":
      store.mergeStoryboardGroup(op.ids as string[]);
      return;
    case "sbConfig":
      store.setStoryboardGroupConfig(op.id as string, op.config as never);
      return;
    case "sbReorder":
      store.reorderStoryboardMember(op.id as string, op.from as number, op.to as number);
      return;
    case "sbAdd":
      store.addStoryboardMembers(
        op.id as string,
        (op.frames as string[]).map((ref) => ({ imageUrl: ref })) as never,
      );
      return;
    case "sbConvert":
      store.convertStoryboardGroupToPlain(op.id as string);
      return;
    case "dupSibling":
      store.duplicateNodeAsSibling(op.id as string, op.index as number);
      return;
    case "dupSiblings":
      store.duplicateNodesAsSiblings(op.ids as string[]);
      return;
    default:
      throw new Error(`unknown op ${op.op}`);
  }
}

function replay(fixture: (typeof fixtures.cases)[number]): unknown[] {
  useCanvasStore.getState().setCanvasData([], []);
  portTypes = new Map();
  known = new Set();
  counter = 0;
  const observations: unknown[] = [];
  for (const op of fixture.ops) {
    apply(op);
    renameCreatedIds();
    observations.push(observe(op.op));
  }
  return observations;
}

const timingOut = process.env.PARITY_TIMING_OUT;

describe("M8-B group parity: donor side", () => {
  it("replays every fixture case and writes observations", async () => {
    const results: Record<string, unknown[]> = {};
    for (const fixture of fixtures.cases) results[fixture.id] = replay(fixture);
    if (outPath) writeFileSync(outPath, `${JSON.stringify({ fixture_set: fixtures.fixture_set, results }, null, 2)}\n`);
    if (timingOut) {
      const timing = await timeCases(
        fixtures.cases,
        (fixture) => {
          replay(fixture);
          const { nodes, edges, history } = useCanvasStore.getState();
          return { nodes, edges, history };
        },
        (value) => serialize(value).length,
      );
      writeFileSync(timingOut, `${JSON.stringify(timing, null, 2)}\n`);
    }

    expect(Object.keys(results)).toHaveLength(fixtures.cases.length);
  });
});
