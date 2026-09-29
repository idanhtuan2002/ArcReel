// The first block runs the donor draft-storage tests (DramaClaw b299bfd9,
// __tests__/features/freezone/canvas-draft-storage.test.ts) against the port's scope-keyed API.
// The donor's undo-history mirror is not kept by the port, so its prune cases use the draft,
// conflict and viewport entries instead.
import { beforeEach, describe, expect, it } from "vitest";

import type { CanvasNode, MutationState } from "../domain/types";
import {
  CANVAS_TTL_MS,
  clearConflictSnapshot,
  DRAFT_MAX_BYTES,
  type DraftInput,
  type DraftScope,
  decideDraftRecovery,
  draftSignature,
  pruneCanvasStorage,
  readConflictSnapshot,
  readDraft,
  readStoredViewport,
  writeConflictSnapshot,
  writeDraft,
  writeStoredViewport,
} from "./draftRecovery";

const EDITED: MutationState = { userEditsSinceHydrate: 1, lastMutationSource: "user_edit", pendingClearIntent: false };

function scope(candidateId: string, projectName = "project-a", userId = "u1"): DraftScope {
  return { userId, projectName, candidateId };
}

function frame(id: string, label = ""): CanvasNode {
  return { id, type: "frame", position: { x: 0, y: 0 }, data: { label } };
}

function input(overrides: Partial<DraftInput> = {}): DraftInput {
  return {
    baseRevision: 1,
    nodes: [],
    edges: [],
    viewport: null,
    metadata: null,
    history: null,
    mutation: EDITED,
    updatedAt: 10,
    ...overrides,
  };
}

describe("draft storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("drops history before giving up on the recoverable canvas content", () => {
    const ok = writeDraft(
      scope("draft-heavy"),
      input({
        baseRevision: 3,
        nodes: [frame("draft-node", "x".repeat(Math.floor(DRAFT_MAX_BYTES / 3)))],
        history: { past: [{ nodes: [frame("history-node", "y".repeat(DRAFT_MAX_BYTES))], edges: [] }], future: [] },
        updatedAt: 1_000,
      }),
    );

    expect(ok).toBe(true);
    const draft = readDraft(scope("draft-heavy"));
    expect(draft?.nodes).toHaveLength(1);
    expect(draft?.history).toBeNull();
  });

  it("does not persist a fake draft when the core content itself is too large", () => {
    const ok = writeDraft(
      scope("draft-too-large"),
      input({ baseRevision: 3, nodes: [frame("draft-node", "x".repeat(DRAFT_MAX_BYTES + 1))], history: { past: [], future: [] } }),
    );

    expect(ok).toBe(false);
    expect(readDraft(scope("draft-too-large"))).toBeNull();
  });

  it("keeps metadata signatures stable across object key order", () => {
    expect(draftSignature([], [], { shotMetadata: { b: 2, a: 1 } })).toBe(
      draftSignature([], [], { shotMetadata: { a: 1, b: 2 } }),
    );
  });

  it("scopes drafts by user, project and candidate", () => {
    writeDraft(scope("canvas-a"), input());

    expect(readDraft(scope("canvas-a"))).not.toBeNull();
    expect(readDraft(scope("canvas-b"))).toBeNull();
    expect(readDraft(scope("canvas-a", "project-b"))).toBeNull();
    expect(readDraft(scope("canvas-a", "project-a", "u2"))).toBeNull();
  });

  it("ignores malformed draft JSON", () => {
    window.localStorage.setItem("arcreel:creative-canvas:draft:u1:project-a:broken", "{not json");

    expect(readDraft(scope("broken"))).toBeNull();
  });

  it("prunes expired drafts without removing fresh ones", () => {
    writeDraft(scope("old"), input({ updatedAt: 1 }));
    writeDraft(scope("fresh"), input({ updatedAt: 7 * 24 * 60 * 60 * 1_000 }));

    pruneCanvasStorage(8 * 24 * 60 * 60 * 1_000 + 2);

    expect(readDraft(scope("old"))).toBeNull();
    expect(readDraft(scope("fresh"))).not.toBeNull();
  });
});

describe("pruneCanvasStorage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("reclaims a draft with a future timestamp (clock skew)", () => {
    const now = 10 * CANVAS_TTL_MS;
    writeDraft(scope("future"), input({ updatedAt: now + 1_000 }));

    pruneCanvasStorage(now);

    expect(readDraft(scope("future"))).toBeNull();
  });

  it("prunes stale conflict snapshots by their ISO timestamp", () => {
    const now = 10 * CANVAS_TTL_MS;
    const snapshot = { nodes: [], edges: [], viewport: null, metadata: null };
    writeConflictSnapshot(scope("stale"), { ...snapshot, timestamp: new Date(now - CANVAS_TTL_MS - 1).toISOString() });
    writeConflictSnapshot(scope("fresh"), { ...snapshot, timestamp: new Date(now - 1).toISOString() });

    pruneCanvasStorage(now);

    expect(readConflictSnapshot(scope("stale"))).toBeNull();
    expect(readConflictSnapshot(scope("fresh"))).not.toBeNull();
  });

  it("clears a conflict snapshot once the user resolved it", () => {
    writeConflictSnapshot(scope("c"), { nodes: [], edges: [], viewport: null, metadata: null, timestamp: new Date(0).toISOString() });

    clearConflictSnapshot(scope("c"));

    expect(readConflictSnapshot(scope("c"))).toBeNull();
  });

  it("keeps viewports (no timestamp) but drops malformed ones", () => {
    writeStoredViewport(scope("ok"), { x: 1, y: 2, zoom: 1 });
    window.localStorage.setItem("arcreel:creative-canvas:viewport:u1:project-a:broken", "{not json");

    pruneCanvasStorage(10 * CANVAS_TTL_MS);

    expect(readStoredViewport(scope("ok"))).toEqual({ x: 1, y: 2, zoom: 1 });
    expect(window.localStorage.getItem("arcreel:creative-canvas:viewport:u1:project-a:broken")).toBeNull();
  });

  it("leaves unrelated keys untouched", () => {
    window.localStorage.setItem("settings-storage", "keep-me");

    pruneCanvasStorage(10 * CANVAS_TTL_MS);

    expect(window.localStorage.getItem("settings-storage")).toBe("keep-me");
  });
});

describe("decideDraftRecovery", () => {
  const remote = [frame("a", "server")];

  function stored(overrides: Partial<DraftInput>) {
    window.localStorage.clear();
    writeDraft(scope("c"), input(overrides));
    const draft = readDraft(scope("c"));
    if (!draft) throw new Error("draft not stored");
    return draft;
  }

  it("loads the server content when there is no draft", () => {
    expect(decideDraftRecovery(null, 3, remote, [], null)).toEqual({ kind: "remote" });
  });

  it("loads the server content when the draft is already saved", () => {
    expect(decideDraftRecovery(stored({ baseRevision: 2, nodes: remote }), 3, remote, [], null)).toEqual({
      kind: "remote",
    });
  });

  it("treats a draft whose metadata the server already holds as saved", () => {
    const draft = stored({ baseRevision: 2, nodes: remote, metadata: { viewportBookmarks: [] } });

    expect(decideDraftRecovery(draft, 3, remote, [], { viewportBookmarks: [], other: 1 }).kind).toBe("remote");
  });

  it("restores a draft edited from the server's current revision", () => {
    const draft = stored({ baseRevision: 3, nodes: [frame("a", "local edit")] });

    expect(decideDraftRecovery(draft, 3, remote, [], null)).toEqual({ kind: "draft", draft });
  });

  it("reports a conflict for a draft edited from another revision, never applying it", () => {
    const draft = stored({ baseRevision: 2, nodes: [frame("a", "local edit")] });

    expect(decideDraftRecovery(draft, 3, remote, [], null)).toEqual({ kind: "conflict", draft });
    expect(decideDraftRecovery({ ...draft, baseRevision: null }, 3, remote, [], null).kind).toBe("conflict");
  });
});
