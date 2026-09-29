/**
 * Donor side of the M8-B save and recovery parity harness. Copied into the
 * pinned DramaClaw checkout with recoveryRunner.ts by run.sh; runs the shared
 * scenarios (PARITY_FIXTURES) on the unmodified donor modules and writes the
 * observations (PARITY_OUT).
 */
import { readFileSync, writeFileSync } from "node:fs";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { registerStorageReclaimer, safeLocalStorageSet } from "@/lib/localStorageQuota";

import {
  holdCanvasAutosave,
  isCanvasAutosaveHeld,
  subscribeCanvasAutosaveRelease,
} from "@/features/freezone/canvasAutosaveHold";
import {
  CANVAS_DRAFT_MAX_BYTES,
  canvasDraftSignature,
  pruneFreezoneCanvasStorage,
  readCanvasDraft,
  writeCanvasDraft,
} from "@/features/freezone/canvasDraftStorage";
import { createCanvasSaveSession } from "@/features/freezone/canvasSaveCoordinator";
import { checkPayloadLimits, classifySaveError, decideSaveAction } from "@/features/freezone/canvasSyncCore";
import { deriveSaveState, useSaveStatusStore } from "@/stores/save-status-store";

import { type RecoveryImpl, type ScenarioCase, runScenario } from "./recoveryRunner";

const fixturesPath = process.env.PARITY_FIXTURES;
const outPath = process.env.PARITY_OUT;
const fixtures = fixturesPath
  ? (JSON.parse(readFileSync(fixturesPath, "utf-8")) as { fixture_set: string; cases: ScenarioCase[] })
  : { fixture_set: "none", cases: [] };

/**
 * The donor's hydrate decision is module-private in useCanvasSync.ts. Its exact
 * source (decideHydrateDraft and the helpers it calls) is copied verbatim into a
 * scratch module next to this harness and imported, so the unmodified donor
 * code runs on the shared fixtures.
 */
type HydrateDecision = (...args: unknown[]) => { kind: string };
let hydrateDecision: HydrateDecision | null = null;

function extractBlock(source: string, start: string): string {
  const begin = source.indexOf(start);
  if (begin < 0) throw new Error(`donor source has no ${start}`);
  let depth = 0;
  let opened = false;
  for (let index = source.indexOf("{", begin); index < source.length; index += 1) {
    if (source[index] === "{") {
      depth += 1;
      opened = true;
    } else if (source[index] === "}") {
      depth -= 1;
      if (opened && depth === 0) return source.slice(begin, index + 1);
    }
  }
  throw new Error(`unterminated ${start}`);
}

async function loadDonorHydrateDecision(): Promise<HydrateDecision> {
  if (hydrateDecision) return hydrateDecision;
  const source = readFileSync("src/features/freezone/useCanvasSync.ts", "utf-8");
  const parts = [
    "const nodeSignatureCache = new WeakMap<object, string>();",
    "const edgeSignatureCache = new WeakMap<object, string>();",
    extractBlock(source, "function nodeSignature("),
    extractBlock(source, "function edgeSignature("),
    extractBlock(source, "function canvasContentSignature("),
    extractBlock(source, "function jsonContainsSubset("),
    `export ${extractBlock(source, "function decideHydrateDraft(")}`,
  ];
  for (const declaration of ["const nodeSignatureCache = new WeakMap<object, string>();", "const edgeSignatureCache = new WeakMap<object, string>();"]) {
    if (!source.includes(declaration)) throw new Error(`donor source changed: ${declaration}`);
  }
  writeFileSync("src/__parity__/extractedHydrate.ts", `// @ts-nocheck\n${parts.join("\n\n")}\n`);
  const target = "/src/__parity__/extractedHydrate.ts";
  const module = (await import(/* @vite-ignore */ target)) as { decideHydrateDraft: HydrateDecision };
  hydrateDecision = module.decideHydrateDraft;
  return hydrateDecision;
}

const DONOR: RecoveryImpl = {
  createSession: (canvasKey, generation, runSave) =>
    createCanvasSaveSession({ canvasKey, generation, runSave: (version) => runSave(version) }),
  decideSaveAction: (snapshot) => decideSaveAction(snapshot as never),
  checkPayloadLimits,
  classifySave: (status, detail) =>
    classifySaveError(status, detail === undefined ? undefined : { detail: { code: undefined } }, "fallback", (key: string) => key)
      .kind,
  setSaveStatus: (scope, status, error) => useSaveStatusStore.getState().setScopeStatus(scope, status as never, error),
  deriveSaveStatus: (scope) => deriveSaveState(useSaveStatusStore.getState().scopes, scope),
  resetSaveStatus: () => useSaveStatusStore.setState({ scopes: {} }),
  safeSet: safeLocalStorageSet,
  registerReclaimer: registerStorageReclaimer,
  installStorage: (storage) => {
    const original = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
    return () => {
      if (original) Object.defineProperty(window, "localStorage", original);
    };
  },
  hold: (project, maxMs) => holdCanvasAutosave(project, maxMs === undefined ? undefined : { maxMs }),
  isHeld: isCanvasAutosaveHeld,
  subscribeRelease: subscribeCanvasAutosaveRelease,
  // The donor key has no user: every user of a project and canvas shares one draft.
  writeDraft: (scope, input) => writeCanvasDraft(scope.project, scope.canvas, input as never),
  readDraft: (scope) => readCanvasDraft(scope.project, scope.canvas),
  corruptDraft: (scope) =>
    window.localStorage.setItem(
      `supertale-freezone:canvas-draft:${encodeURIComponent(scope.project)}:${encodeURIComponent(scope.canvas)}`,
      "{not json",
    ),
  decideHydrate: async (draft, remoteRevision, remoteNodes, remoteMetadata) => {
    const hydrate = await loadDonorHydrateDecision();
    const nodes = remoteNodes as never[];
    const signature = canvasDraftSignature(nodes, [], remoteMetadata);
    return hydrate(draft, remoteRevision, signature, nodes, [], remoteMetadata, (key: string) => key).kind;
  },
  prune: (now) => pruneFreezoneCanvasStorage(now),
  draftMaxBytes: CANVAS_DRAFT_MAX_BYTES,
  clearStorage: () => window.localStorage.clear(),
  advanceTimers: (ms) => vi.advanceTimersByTime(ms),
};

describe("M8-B save and recovery parity: donor side", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-29T00:00:00Z"));
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("runs every scenario and writes observations", async () => {
    const results: Record<string, unknown[]> = {};
    for (const fixture of fixtures.cases) results[fixture.id] = await runScenario(DONOR, fixture);
    if (outPath) writeFileSync(outPath, `${JSON.stringify({ fixture_set: fixtures.fixture_set, results }, null, 2)}\n`);

    expect(Object.keys(results)).toHaveLength(fixtures.cases.length);
  });
});
