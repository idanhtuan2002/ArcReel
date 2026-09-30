import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { registerStorageReclaimer, safeLocalStorageSet } from "../recovery/storageQuota";

import { type RecoveryImpl, type ScenarioCase, runScenario } from "../../../../../tools/parity/dramaclaw/recoveryRunner";
import { storageEntries } from "../../../../../tools/parity/dramaclaw/timingRunner";
import { timingOut, writeTiming } from "./timing";
import fixtures from "../__fixtures__/parity/recovery.json";
import { holdCanvasAutosave, isCanvasAutosaveHeld, subscribeCanvasAutosaveRelease } from "../recovery/autosaveHold";
import type { CanvasNode } from "../domain/types";
import {
  DRAFT_MAX_BYTES,
  type DraftInput,
  type StoredDraft,
  decideDraftRecovery,
  pruneCanvasStorage,
  readDraft,
  writeDraft,
} from "../recovery/draftRecovery";
import { createCanvasSaveSession } from "../recovery/saveCoordinator";
import { type SaveSnapshot, checkPayloadLimits, classifySaveOutcome, decideSaveAction } from "../recovery/saveDecision";
import { deriveSaveState, useSaveStatusStore } from "../state/saveStatusStore";

const cases = fixtures.cases as unknown as ScenarioCase[];
const scopeOf = (scope: { user: string; project: string; canvas: string }) => ({
  userId: scope.user,
  projectName: scope.project,
  candidateId: scope.canvas,
});

const PORT: RecoveryImpl = {
  createSession: (canvasKey, generation, runSave) =>
    createCanvasSaveSession({ canvasKey, generation, runSave: (version) => runSave(version) }),
  decideSaveAction: (snapshot) => decideSaveAction(snapshot as unknown as SaveSnapshot),
  checkPayloadLimits,
  classifySave: (status, detail) => classifySaveOutcome(status, detail === undefined ? undefined : { detail }, "fallback").kind,
  setSaveStatus: (scope, status, error) =>
    useSaveStatusStore.getState().setScopeStatus(scope, status as "idle" | "saving" | "saved" | "error", error),
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
  writeDraft: (scope, input) => writeDraft(scopeOf(scope), input as unknown as DraftInput),
  readDraft: (scope) => readDraft(scopeOf(scope)),
  corruptDraft: (scope) =>
    window.localStorage.setItem(`arcreel:creative-canvas:draft:${scope.user}:${scope.project}:${scope.canvas}`, "{not json"),
  decideHydrate: (draft, remoteRevision, remoteNodes, remoteMetadata) =>
    Promise.resolve(
      decideDraftRecovery(
        draft as StoredDraft | null,
        remoteRevision,
        remoteNodes as CanvasNode[],
        [],
        remoteMetadata,
      ).kind,
    ),
  prune: (now) => pruneCanvasStorage(now),
  draftMaxBytes: DRAFT_MAX_BYTES,
  clearStorage: () => window.localStorage.clear(),
  advanceTimers: (ms) => vi.advanceTimersByTime(ms),
};

describe("save and recovery parity scenarios on the port", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-29T00:00:00Z"));
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("matches the recorded port observations (the parity harness input)", async () => {
    const results: Record<string, unknown[]> = {};
    for (const fixture of cases) results[fixture.id] = await runScenario(PORT, fixture);

    await expect(`${JSON.stringify({ fixture_set: fixtures.fixture_set, results }, null, 2)}\n`).toMatchFileSnapshot(
      "../__fixtures__/parity/recovery.port.json",
    );
  });

  it.runIf(Boolean(timingOut))("records the timing of every case for the parity report", async () => {
    await expect(writeTiming(cases, async (fixture) => {
        const observations = await runScenario(PORT, fixture);
        return { final: observations.at(-1) ?? null, storage: storageEntries() };
      })).resolves.toBeUndefined();
  });
});
