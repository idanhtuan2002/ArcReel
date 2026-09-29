/**
 * Donor side of the M8-B graph and history parity harness.
 *
 * Copied into the pinned DramaClaw checkout (frontend/src/__parity__/) by
 * tools/parity/dramaclaw/run.sh and run with the donor's own vitest. It replays
 * the canonical fixtures (PARITY_FIXTURES) against the unmodified donor store
 * and writes one observation per operation (PARITY_OUT), in the same shape as
 * the port adapter (frontend/src/features/creative-canvas/__parity__/graphAdapter.ts).
 *
 * Donor-generated ids (addNode, onConnect) are renamed to the fixture ids right
 * after the operation; the rename touches only current nodes/edges, never history.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { serialize } from "node:v8";

import type { NodeChange } from "@xyflow/react";
import { describe, expect, it } from "vitest";
import { timeCases } from "./timingRunner";

import { CANVAS_NODE_TYPES } from "@/features/canvas/domain/canvasNodes";
import { useCanvasStore, type CanvasEdge, type CanvasNode } from "@/stores/canvasStore";

type PortType = "beat" | "note" | "frame" | "clip" | "audio" | "group";

const TO_DONOR: Record<PortType, string> = {
  beat: CANVAS_NODE_TYPES.textAnnotation,
  note: CANVAS_NODE_TYPES.textAnnotation,
  frame: CANVAS_NODE_TYPES.exportImage,
  clip: CANVAS_NODE_TYPES.video,
  audio: CANVAS_NODE_TYPES.audio,
  group: CANVAS_NODE_TYPES.group,
};

interface FixtureNode {
  id: string;
  type: PortType;
  parentId?: string;
  x?: number;
  y?: number;
}

type Op = { op: string; [key: string]: unknown };

interface FixtureCase {
  id: string;
  ops: Op[];
}

const fixturesPath = process.env.PARITY_FIXTURES;
const outPath = process.env.PARITY_OUT;
const fixtures = fixturesPath
  ? (JSON.parse(readFileSync(fixturesPath, "utf-8")) as { fixture_set: string; cases: FixtureCase[] })
  : { fixture_set: "none", cases: [] };

// The port type of every node id seen, so observations report port types.
let portTypes = new Map<string, PortType>();

function toDonorNode(item: FixtureNode): CanvasNode {
  portTypes.set(item.id, item.type);
  return {
    id: item.id,
    type: TO_DONOR[item.type],
    position: { x: item.x ?? 0, y: item.y ?? 0 },
    data: {},
    ...(item.parentId ? { parentId: item.parentId } : {}),
  } as unknown as CanvasNode;
}

function toDonorEdge(item: { id: string; source: string; target: string }): CanvasEdge {
  return { id: item.id, source: item.source, target: item.target } as CanvasEdge;
}

function renameLastNode(fixtureId: string): void {
  const state = useCanvasStore.getState();
  const last = state.nodes[state.nodes.length - 1];
  useCanvasStore.setState({ nodes: [...state.nodes.slice(0, -1), { ...last, id: fixtureId }] });
}

function renameNewEdge(before: readonly CanvasEdge[], fixtureId: string): void {
  const state = useCanvasStore.getState();
  const known = new Set(before.map((edge) => edge.id));
  useCanvasStore.setState({
    edges: state.edges.map((edge) => (known.has(edge.id) ? edge : { ...edge, id: fixtureId })),
  });
}

function observe(op: string) {
  const state = useCanvasStore.getState();
  return {
    op,
    nodes: state.nodes.map((node) => ({
      id: node.id,
      type: portTypes.get(node.id) ?? `donor:${node.type}`,
      parentId: node.parentId ?? null,
      x: node.position.x,
      y: node.position.y,
    })),
    edges: state.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle ?? "source",
      targetHandle: edge.targetHandle ?? "target",
    })),
    past: state.history.past.length,
    future: state.history.future.length,
    selected: state.selectedNodeId,
    edits: state.userEditsSinceHydrate,
    source: state.lastMutationSource,
    pendingClear: state.pendingClearIntent,
  };
}

function addFixtureNode(item: FixtureNode): void {
  portTypes.set(item.id, item.type);
  useCanvasStore.getState().addNode(TO_DONOR[item.type] as never, { x: item.x ?? 0, y: item.y ?? 0 }, {});
  renameLastNode(item.id);
}

function apply(op: Op): void {
  const store = useCanvasStore.getState();
  switch (op.op) {
    case "load":
      store.setCanvasData(
        (op.nodes as FixtureNode[]).map(toDonorNode),
        (op.edges as { id: string; source: string; target: string }[]).map(toDonorEdge),
      );
      return;
    case "hydrate":
      store.hydrateCanvasDraft({
        nodes: (op.nodes as FixtureNode[]).map(toDonorNode),
        edges: (op.edges as { id: string; source: string; target: string }[]).map(toDonorEdge),
        history: null,
        mutation: op.mutation as never,
      });
      return;
    case "add":
      addFixtureNode(op.node as FixtureNode);
      return;
    case "addMany":
      for (let index = 0; index < (op.count as number); index += 1) {
        addFixtureNode({ id: `${op.prefix as string}${index}`, type: "note" });
      }
      return;
    case "connect": {
      const before = store.edges;
      store.onConnect({ source: op.source as string, target: op.target as string, sourceHandle: null, targetHandle: null });
      renameNewEdge(before, op.id as string);
      return;
    }
    case "delete":
      store.deleteNodes(op.ids as string[]);
      return;
    case "deleteEdge":
      store.deleteEdge(op.id as string);
      return;
    case "clear":
      store.clearCanvas();
      return;
    case "ack":
      store.acknowledgePendingClear();
      return;
    case "select":
      store.setSelectedNode(op.id as string | null);
      return;
    case "undo":
      store.undo();
      return;
    case "redo":
      store.redo();
      return;
    case "undoMany":
      for (let index = 0; index < (op.count as number); index += 1) useCanvasStore.getState().undo();
      return;
    case "redoMany":
      for (let index = 0; index < (op.count as number); index += 1) useCanvasStore.getState().redo();
      return;
    case "changes":
      store.onNodesChange(op.changes as NodeChange<CanvasNode>[]);
      return;
    case "restoreHistoryOf": {
      const past = Array.from({ length: op.count as number }, (_, index) => ({
        nodes: [toDonorNode({ id: `${op.prefix as string}${index}`, type: "note" })],
        edges: [],
      }));
      store.restoreHistory({ past, future: [] });
      return;
    }
    default:
      throw new Error(`unknown op ${op.op}`);
  }
}

function replay(fixture: (typeof fixtures.cases)[number]): unknown[] {
  useCanvasStore.getState().setCanvasData([], []);
  portTypes = new Map();
  const observations: unknown[] = [];
  for (const op of fixture.ops) {
    apply(op);
    observations.push(observe(op.op));
  }
  return observations;
}

const timingOut = process.env.PARITY_TIMING_OUT;

describe("M8-B graph parity: donor side", () => {
  it("replays every fixture case and writes observations", async () => {
    const results: Record<string, unknown[]> = {};
    for (const fixture of fixtures.cases) results[fixture.id] = replay(fixture);
    if (outPath) writeFileSync(outPath, JSON.stringify({ fixture_set: fixtures.fixture_set, results }, null, 2));
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
