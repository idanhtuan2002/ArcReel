/**
 * Port side of the donor parity harness for pure functions. Each fixture call
 * names a function and its JSON arguments; `{"$num": "NaN"|"Infinity"|"-Infinity"}`
 * encodes the numbers JSON cannot. The donor side
 * (tools/parity/dramaclaw/functions.parity.test.ts) calls the donor functions of
 * the same names with the same arguments.
 */

import {
  bookmarkCenterInFlow,
  bookmarkIndexToDigit,
  createEmptyBookmarks,
  digitToBookmarkIndex,
  isViewportBookmark,
  normalizeBookmarks,
  projectToMinimap,
} from "../domain/bookmarks";
import {
  GROUP_COLOR_PRESETS,
  groupColorBackground,
  groupColorBorder,
} from "../domain/groupColors";
import {
  collectBatchDeletableIds,
  collectDuplicableIds,
} from "../domain/groupSelection";
import {
  computeStoryboardBoardLayout,
  computeStoryboardCell,
  computeStoryboardGridLayout,
  resolveStoryboardAspectRatio,
  resolveStoryboardCols,
  storyboardSlotRect,
} from "../domain/storyboardLayout";
import { computeAutoLayout } from "../domain/layout";
import type { CanvasEdge, CanvasNode } from "../domain/types";

export interface FunctionCall {
  fn: string;
  args: unknown[];
}

export interface FunctionCase {
  id: string;
  behaviors: string[];
  calls: FunctionCall[];
}

export function decode(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(decode);
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record.$num === "string" && Object.keys(record).length === 1)
      return Number(record.$num);
    return Object.fromEntries(
      Object.entries(record).map(([key, item]) => [key, decode(item)]),
    );
  }
  return value;
}

/** Fixture nodes carry only id, type and parentId; the functions read nothing else. */
function nodes(value: unknown): CanvasNode[] {
  return (
    value as {
      id: string;
      type: CanvasNode["type"];
      parentId?: string;
      x?: number;
      y?: number;
      w?: number;
      h?: number;
      mw?: number;
      mh?: number;
    }[]
  ).map((item) => ({
    id: item.id,
    type: item.type,
    position: { x: item.x ?? 0, y: item.y ?? 0 },
    data: {},
    ...(item.parentId ? { parentId: item.parentId } : {}),
    ...(item.w !== undefined ? { width: item.w } : {}),
    ...(item.h !== undefined ? { height: item.h } : {}),
    ...(item.mw !== undefined ? { measured: { width: item.mw, height: item.mh } } : {}),
  }));
}

type Args = readonly unknown[];
const num = (value: unknown): number => value as number;
const str = (value: unknown): string => value as string;

const FUNCTIONS: Record<string, (args: Args) => unknown> = {
  resolveStoryboardAspectRatio: ([key]) =>
    resolveStoryboardAspectRatio((key as string | null) ?? undefined),
  resolveStoryboardCols: ([count, requested]) =>
    resolveStoryboardCols(num(count), requested as number | undefined),
  computeStoryboardCell: ([width, height, key]) =>
    computeStoryboardCell(num(width), num(height), key as string | undefined),
  storyboardSlotRect: ([index, cols, width, height]) =>
    storyboardSlotRect(num(index), num(cols), num(width), num(height)),
  computeStoryboardGridLayout: ([input]) =>
    computeStoryboardGridLayout(
      input as Parameters<typeof computeStoryboardGridLayout>[0],
    ),
  computeStoryboardBoardLayout: ([input]) =>
    computeStoryboardBoardLayout(
      input as Parameters<typeof computeStoryboardBoardLayout>[0],
    ),
  createEmptyBookmarks: () => createEmptyBookmarks(),
  digitToBookmarkIndex: ([digit]) => digitToBookmarkIndex(str(digit)),
  bookmarkIndexToDigit: ([index]) => bookmarkIndexToDigit(num(index)),
  isViewportBookmark: ([value]) => isViewportBookmark(value),
  normalizeBookmarks: ([value]) => normalizeBookmarks(value),
  bookmarkCenterInFlow: ([bookmark, size]) =>
    bookmarkCenterInFlow(
      bookmark as Parameters<typeof bookmarkCenterInFlow>[0],
      size as Parameters<typeof bookmarkCenterInFlow>[1],
    ),
  projectToMinimap: ([point, viewBox, size]) =>
    projectToMinimap(
      point as Parameters<typeof projectToMinimap>[0],
      viewBox as Parameters<typeof projectToMinimap>[1],
      size as Parameters<typeof projectToMinimap>[2],
    ),
  collectBatchDeletableIds: ([items, selected]) =>
    collectBatchDeletableIds(nodes(items), selected as string[]),
  collectDuplicableIds: ([items, selected]) =>
    collectDuplicableIds(nodes(items), selected as string[]),
  computeAutoLayout: ([items, edges]) => computeAutoLayout(nodes(items), edges as CanvasEdge[]),
  groupColorPresets: () =>
    GROUP_COLOR_PRESETS.map(({ key, value }) => ({ key, value })),
  groupColorBackground: ([color]) =>
    groupColorBackground(color as string | null),
  groupColorBorder: ([color]) => groupColorBorder(color as string | null),
};

/** One JSON-safe result per call: `{value}` or `{error}` when the function throws. */
export function runFunctionCase(fixture: FunctionCase): unknown[] {
  return fixture.calls.map((call) => {
    const fn = FUNCTIONS[call.fn];
    if (!fn) return { error: `unknown function ${call.fn}` };
    try {
      const value = fn(decode(call.args) as unknown[]);
      return { value: value === undefined ? { $undefined: true } : value };
    } catch (error) {
      return { error: error instanceof Error ? error.message : String(error) };
    }
  });
}
