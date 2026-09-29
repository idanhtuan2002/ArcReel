/**
 * Donor side of the M8-B pure-function parity harness. Copied into the pinned
 * DramaClaw checkout by tools/parity/dramaclaw/run.sh. Calls the unmodified
 * donor functions named by the fixtures (PARITY_FIXTURES) and writes one result
 * per call (PARITY_OUT), in the shape of the port adapter
 * (frontend/src/features/creative-canvas/__parity__/functionsAdapter.ts).
 */
import { readFileSync, writeFileSync } from "node:fs";

import { describe, expect, it } from "vitest";
import { timeCases } from "./timingRunner";

import { computeAutoLayout } from "@/features/canvas/application/autoLayout";
import {
  LOW_DETAIL_ZOOM_THRESHOLD,
  isLowDetailZoom,
  isNodeMediaActive,
  setNodeMediaActive,
} from "@/features/canvas/application/canvasLod";
import { CANVAS_NODE_TYPES, type CanvasEdge, type CanvasNode } from "@/features/canvas/domain/canvasNodes";
import { GROUP_COLOR_PRESETS, groupColorBackground, groupColorBorder } from "@/features/canvas/domain/groupColors";
import { collectBatchDeletableIds } from "@/features/canvas/domain/groupSelectionDelete";
import { collectDuplicableIds } from "@/features/canvas/domain/groupSelectionDuplicate";
import {
  computeStoryboardBoardLayout,
  computeStoryboardCell,
  computeStoryboardGridLayout,
  resolveStoryboardAspectRatio,
  resolveStoryboardCols,
  storyboardSlotRect,
} from "@/features/canvas/domain/storyboardGroup";
import {
  bookmarkCenterInFlow,
  bookmarkIndexToDigit,
  createEmptyBookmarks,
  digitToBookmarkIndex,
  isViewportBookmark,
  normalizeBookmarks,
  projectToMinimap,
} from "@/features/canvas/domain/viewportBookmarks";

const TO_DONOR: Record<string, string> = {
  beat: CANVAS_NODE_TYPES.textAnnotation,
  note: CANVAS_NODE_TYPES.textAnnotation,
  frame: CANVAS_NODE_TYPES.exportImage,
  clip: CANVAS_NODE_TYPES.video,
  audio: CANVAS_NODE_TYPES.audio,
  group: CANVAS_NODE_TYPES.group,
};

function decode(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(decode);
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record.$num === "string" && Object.keys(record).length === 1) return Number(record.$num);
    return Object.fromEntries(Object.entries(record).map(([key, item]) => [key, decode(item)]));
  }
  return value;
}

function nodes(value: unknown): CanvasNode[] {
  return (
    value as { id: string; type: string; parentId?: string; x?: number; y?: number; w?: number; h?: number; mw?: number; mh?: number }[]
  ).map((item) => ({
    id: item.id,
    type: TO_DONOR[item.type],
    position: { x: item.x ?? 0, y: item.y ?? 0 },
    data: {},
    ...(item.parentId ? { parentId: item.parentId } : {}),
    ...(item.w !== undefined ? { width: item.w } : {}),
    ...(item.h !== undefined ? { height: item.h } : {}),
    ...(item.mw !== undefined ? { measured: { width: item.mw, height: item.mh } } : {}),
  })) as unknown as CanvasNode[];
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- fixture arguments are untyped JSON
const FUNCTIONS: Record<string, (...args: any[]) => unknown> = {
  resolveStoryboardAspectRatio: (key) => resolveStoryboardAspectRatio(key ?? undefined),
  resolveStoryboardCols: (count, requested) => resolveStoryboardCols(count, requested),
  computeStoryboardCell: (width, height, key) => computeStoryboardCell(width, height, key),
  storyboardSlotRect: (index, cols, width, height) => storyboardSlotRect(index, cols, width, height),
  computeStoryboardGridLayout: (input) => computeStoryboardGridLayout(input),
  computeStoryboardBoardLayout: (input) => computeStoryboardBoardLayout(input),
  createEmptyBookmarks: () => createEmptyBookmarks(),
  digitToBookmarkIndex: (digit) => digitToBookmarkIndex(digit),
  bookmarkIndexToDigit: (index) => bookmarkIndexToDigit(index),
  isViewportBookmark: (value) => isViewportBookmark(value),
  normalizeBookmarks: (value) => normalizeBookmarks(value),
  bookmarkCenterInFlow: (bookmark, size) => bookmarkCenterInFlow(bookmark, size),
  projectToMinimap: (point, viewBox, size) => projectToMinimap(point, viewBox, size),
  collectBatchDeletableIds: (items, selected) => collectBatchDeletableIds(nodes(items), selected),
  collectDuplicableIds: (items, selected) => collectDuplicableIds(nodes(items), selected),
  computeAutoLayout: (items, edges) => computeAutoLayout(nodes(items), edges as CanvasEdge[]),
  groupColorPresets: () => GROUP_COLOR_PRESETS.map(({ key, value }) => ({ key, value })),
  groupColorBackground: (color) => groupColorBackground(color),
  groupColorBorder: (color) => groupColorBorder(color),
  lowDetailZoomThreshold: () => LOW_DETAIL_ZOOM_THRESHOLD,
  isLowDetailZoom: (zoom) => isLowDetailZoom(zoom),
  mediaActiveAfter: (ops: [string, boolean][], queries: string[]) => {
    for (const [id, active] of ops) setNodeMediaActive(id, active);
    const out = queries.map((id) => isNodeMediaActive(id));
    for (const [id] of ops) setNodeMediaActive(id, false);
    return out;
  },
};

interface FunctionCase {
  id: string;
  calls: { fn: string; args: unknown[] }[];
}

const fixturesPath = process.env.PARITY_FIXTURES;
const outPath = process.env.PARITY_OUT;
const fixtures = fixturesPath
  ? (JSON.parse(readFileSync(fixturesPath, "utf-8")) as { fixture_set: string; cases: FunctionCase[] })
  : { fixture_set: "none", cases: [] };

function replay(fixture: FunctionCase): unknown[] {
  return fixture.calls.map((call) => {
    const fn = FUNCTIONS[call.fn];
    if (!fn) return { error: `unknown function ${call.fn}` };
    try {
      const value = fn(...(decode(call.args) as unknown[]));
      return { value: value === undefined ? { $undefined: true } : value };
    } catch (error) {
      return { error: error instanceof Error ? error.message : String(error) };
    }
  });
}

const timingOut = process.env.PARITY_TIMING_OUT;

describe("M8-B pure-function parity: donor side", () => {
  it("calls every fixture function and writes results", async () => {
    const results: Record<string, unknown[]> = {};
    for (const fixture of fixtures.cases) results[fixture.id] = replay(fixture);
    if (outPath) writeFileSync(outPath, `${JSON.stringify({ fixture_set: fixtures.fixture_set, results }, null, 2)}\n`);
    if (timingOut) writeFileSync(timingOut, `${JSON.stringify(await timeCases(fixtures.cases, replay), null, 2)}\n`);

    expect(Object.keys(results)).toHaveLength(fixtures.cases.length);
  });
});
