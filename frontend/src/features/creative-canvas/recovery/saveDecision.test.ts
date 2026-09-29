// Donor tests (DramaClaw b299bfd9, __tests__/features/freezone/canvasSyncCore.test.ts) run on the port:
// the decideSaveAction and checkPayloadLimits cases, unchanged. The donor's buildSavePayload,
// sanitizePreviewImageUrls and classifySaveError cases cover donor-only payloads and error codes;
// classifySaveOutcome has its own cases below.
import { describe, expect, it } from "vitest";

import {
  checkPayloadLimits,
  classifySaveOutcome,
  decideSaveAction,
  describePayloadViolation,
  MAX_BODY_BYTES,
  MAX_EDGES,
  MAX_NODES,
  type SaveSnapshot,
} from "./saveDecision";

// Helper to build a snapshot with sensible defaults; tests override only what
// they care about so the intent of each case is obvious from the diff.
function snapshot(overrides: Partial<SaveSnapshot> = {}): SaveSnapshot {
  return {
    hydrated: true,
    switching: false,
    nodeCount: 1,
    edgeCount: 0,
    lastRemoteNodeCount: 1,
    userEditsSinceHydrate: 0,
    lastMutationSource: null,
    pendingClearIntent: false,
    ...overrides,
  };
}

describe("decideSaveAction", () => {
  it("skips when hydrate has not finished", () => {
    expect(decideSaveAction(snapshot({ hydrated: false }))).toEqual({
      kind: "skip",
      reason: "not_hydrated",
    });
  });

  it("skips while canvas/project is switching", () => {
    expect(decideSaveAction(snapshot({ switching: true }))).toEqual({
      kind: "skip",
      reason: "switching",
    });
  });

  it("sends a normal autosave when local + remote both have nodes", () => {
    expect(
      decideSaveAction(snapshot({ nodeCount: 3, lastRemoteNodeCount: 3 })),
    ).toEqual({
      kind: "send",
      saveSource: "autosave",
      allowEmptyOverwrite: false,
    });
  });

  it("sends a normal autosave when both sides are empty (noop new canvas)", () => {
    expect(
      decideSaveAction(snapshot({ nodeCount: 0, lastRemoteNodeCount: 0 })),
    ).toEqual({
      kind: "send",
      saveSource: "autosave",
      allowEmptyOverwrite: false,
    });
  });

  it("auto-promotes manual_clear when user explicitly cleared the canvas", () => {
    expect(
      decideSaveAction(
        snapshot({
          nodeCount: 0,
          lastRemoteNodeCount: 5,
          lastMutationSource: "manual_clear",
          pendingClearIntent: true,
        }),
      ),
    ).toEqual({
      kind: "send",
      saveSource: "manual_clear",
      allowEmptyOverwrite: true,
    });
  });

  it("auto-promotes manual_clear when pendingClearIntent alone is set", () => {
    // Edge case: the clear store action ran but the dispatched mutation source
    // was already overwritten by a follow-up edit that did not change node count.
    expect(
      decideSaveAction(
        snapshot({
          nodeCount: 0,
          lastRemoteNodeCount: 2,
          lastMutationSource: null,
          pendingClearIntent: true,
        }),
      ),
    ).toMatchObject({
      kind: "send",
      saveSource: "manual_clear",
      allowEmptyOverwrite: true,
    });
  });

  it("auto-promotes manual_clear when user deleted nodes one by one to empty", () => {
    expect(
      decideSaveAction(
        snapshot({
          nodeCount: 0,
          lastRemoteNodeCount: 4,
          lastMutationSource: "delete_to_empty",
          userEditsSinceHydrate: 4,
        }),
      ),
    ).toEqual({
      kind: "send",
      saveSource: "manual_clear",
      allowEmptyOverwrite: true,
    });
  });

  it("blocks dangerous_empty when local emptied without a clear intent (HMR reset)", () => {
    // The user did not touch anything (userEditsSinceHydrate === 0,
    // lastMutationSource === null) but nodes are suddenly empty — Zustand
    // reload accident.
    expect(
      decideSaveAction(
        snapshot({
          nodeCount: 0,
          lastRemoteNodeCount: 7,
          userEditsSinceHydrate: 0,
          lastMutationSource: null,
        }),
      ),
    ).toEqual({
      kind: "block",
      reason: "dangerous_empty",
      lastRemoteNodeCount: 7,
    });
  });

  it("blocks dangerous_empty when user edited but store later reset to empty", () => {
    // User made some edits, then HMR / Zustand reset wiped the store. The
    // last mutation source remembers a real edit, not a clear, so the empty
    // state is NOT trustworthy.
    const decision = decideSaveAction(
      snapshot({
        nodeCount: 0,
        lastRemoteNodeCount: 7,
        userEditsSinceHydrate: 5,
        lastMutationSource: "user_edit",
      }),
    );
    expect(decision).toMatchObject({ kind: "block", reason: "dangerous_empty" });
  });

  it("does not block when the canvas was never non-empty on the server", () => {
    // Brand-new canvas: even if local is empty, there is nothing to lose.
    expect(
      decideSaveAction(
        snapshot({
          nodeCount: 0,
          lastRemoteNodeCount: 0,
          userEditsSinceHydrate: 0,
          lastMutationSource: null,
        }),
      ),
    ).toMatchObject({ kind: "send", saveSource: "autosave" });
  });
});


describe("checkPayloadLimits", () => {
  it("returns null when every dimension is within bounds", () => {
    expect(checkPayloadLimits(10, 20, 1024)).toBeNull();
    // Body-size check is opt-in: passing null means "do not check".
    expect(checkPayloadLimits(MAX_NODES, MAX_EDGES, null)).toBeNull();
  });

  it("flags node count as the first violation when over the cap", () => {
    const violation = checkPayloadLimits(MAX_NODES + 1, 0, null);
    expect(violation).toEqual({
      field: "nodes",
      actual: MAX_NODES + 1,
      limit: MAX_NODES,
    });
  });

  it("flags edge count when nodes are within bounds", () => {
    const violation = checkPayloadLimits(10, MAX_EDGES + 1, null);
    expect(violation).toEqual({
      field: "edges",
      actual: MAX_EDGES + 1,
      limit: MAX_EDGES,
    });
  });

  it("flags body size only when counts pass and a size is supplied", () => {
    const violation = checkPayloadLimits(10, 10, MAX_BODY_BYTES + 1);
    expect(violation).toEqual({
      field: "body",
      actual: MAX_BODY_BYTES + 1,
      limit: MAX_BODY_BYTES,
    });
  });

  it("prefers node violation over body violation when both exceed", () => {
    const violation = checkPayloadLimits(
      MAX_NODES + 1,
      0,
      MAX_BODY_BYTES + 1024,
    );
    expect(violation?.field).toBe("nodes");
  });
});


describe("describePayloadViolation", () => {
  const t = (key: string, params?: Record<string, unknown>) => `${key} ${JSON.stringify(params)}`;

  it("names the violated field and its numbers", () => {
    expect(describePayloadViolation({ field: "nodes", actual: 50_001, limit: MAX_NODES }, t)).toBe(
      'creativeCanvas.save.nodesOverLimit {"actual":50001,"limit":50000}',
    );
    expect(describePayloadViolation({ field: "edges", actual: 200_001, limit: MAX_EDGES }, t)).toBe(
      'creativeCanvas.save.edgesOverLimit {"actual":200001,"limit":200000}',
    );
  });

  it("renders the body size in KB", () => {
    expect(describePayloadViolation({ field: "body", actual: 6 * 1024 * 1024, limit: MAX_BODY_BYTES }, t)).toBe(
      'creativeCanvas.save.bodyOverLimit {"actual":6144,"limit":5120}',
    );
  });
});

describe("classifySaveOutcome", () => {
  it("maps a moved head (409) to a conflict carrying the server's localized detail", () => {
    expect(classifySaveOutcome(409, { detail: "The candidate changed" }, "fallback")).toEqual({
      kind: "conflict",
      message: "The candidate changed",
    });
  });

  it("maps 404 to not_found and 422 to invalid", () => {
    expect(classifySaveOutcome(404, { detail: "Not found" }, "fallback").kind).toBe("not_found");
    expect(classifySaveOutcome(422, { detail: [{ loc: ["body"] }] }, "fallback")).toEqual({
      kind: "invalid",
      message: "fallback",
    });
  });

  it("retries network failures, timeouts, throttling and server errors", () => {
    for (const status of [null, 408, 429, 500, 503]) {
      expect(classifySaveOutcome(status, undefined, "fallback").kind).toBe("retry");
    }
  });

  it("treats any other status as an error", () => {
    expect(classifySaveOutcome(400, { detail: "" }, "fallback")).toEqual({ kind: "error", message: "fallback" });
  });
});
