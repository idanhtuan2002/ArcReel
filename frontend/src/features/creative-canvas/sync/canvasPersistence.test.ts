import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "@/api";

import { digestPayload } from "../api/canonical";
import { toCanvasPayload } from "../api/serialize";
import type { CandidateHead, CanvasRevisionWire, LineageBinding } from "../api/types";
import { createEmptyBookmarks } from "../domain/bookmarks";
import { addNode, clearCanvas } from "../domain/graph";
import type { CanvasNode } from "../domain/types";
import { readConflictSnapshot, readDraft, writeConflictSnapshot, writeDraft } from "../recovery/draftRecovery";
import { useCanvasStore } from "../state/canvasStore";
import { canvasSaveScope, deriveSaveState, useSaveStatusStore } from "../state/saveStatusStore";
import { AUTOSAVE_DELAY_MS, CanvasPersistence, type PersistenceDeps, RETRY_DELAY_MS } from "./canvasPersistence";

const PROJECT = "demo";
const CANDIDATE = "canvas-episode-1";
const SCOPE = { userId: "default", projectName: PROJECT, candidateId: CANDIDATE };
const DIGEST = (fill: string) => `sha256:${fill.repeat(64)}` as const;

function lineage(basis = "1"): LineageBinding {
  return {
    project_name: PROJECT,
    content_basis_digest: DIGEST(basis),
    approved_master_id: null,
    approved_master_digest: null,
    creative_profile_id: "arcreel.host",
    creative_profile_version: "1",
    policy_digest: DIGEST("2"),
  };
}

function note(id: string, label = id): CanvasNode {
  return { id, type: "note", position: { x: 0, y: 0 }, data: { label } };
}

const conflict = () => new ApiRequestError("The canvas changed elsewhere.", undefined, 409);

/** The M8-A append rules: genesis without a parent, then parent = head, revision = head + 1 and the head CAS. */
class FakeServer {
  lineage = lineage();
  heads = new Map<string, CandidateHead>();
  revisions = new Map<string, CanvasRevisionWire[]>();
  failNext: number[] = [];

  getExplorationContext = vi.fn(() => Promise.resolve({ lineage: this.lineage, created_by: "default" }));

  getCandidateHead = vi.fn((_project: string, id: string) => {
    const head = this.heads.get(id);
    return head ? Promise.resolve({ ...head }) : Promise.reject(new ApiRequestError("missing", undefined, 404));
  });

  getCanvasRevision = vi.fn((_project: string, id: string, revision: number) =>
    Promise.resolve(structuredClone((this.revisions.get(id) ?? [])[revision - 1])),
  );

  appendCanvasRevision = vi.fn(
    async (_project: string, revision: CanvasRevisionWire, expected: number | null): Promise<CandidateHead> => {
      const status = this.failNext.shift();
      if (status === 409) throw conflict();
      if (status) throw new ApiRequestError("unavailable", undefined, status);
      if ((await digestPayload(revision.payload, revision.lineage)) !== revision.payload_digest) throw conflict();
      const head = this.heads.get(revision.candidate_id);
      if (revision.revision === 1 ? head !== undefined || revision.parent_revision !== null || expected !== null : !head) {
        throw conflict();
      }
      if (
        head &&
        (revision.parent_revision !== head.current_revision ||
          revision.revision !== head.current_revision + 1 ||
          expected !== head.head_version)
      ) {
        throw conflict();
      }
      const next = { candidate_id: revision.candidate_id, current_revision: revision.revision, head_version: revision.revision };
      this.heads.set(revision.candidate_id, next);
      this.revisions.set(revision.candidate_id, [...(this.revisions.get(revision.candidate_id) ?? []), structuredClone(revision)]);
      return { ...next };
    },
  );

  /** Another tab saves `nodes` on top of the current head. */
  async saveElsewhere(nodes: CanvasNode[]): Promise<void> {
    const head = this.heads.get(CANDIDATE) ?? null;
    const payload = JSON.parse(JSON.stringify(toCanvasPayload(nodes, [], createEmptyBookmarks())));
    await this.appendCanvasRevision(
      PROJECT,
      {
        candidate_id: CANDIDATE,
        revision: head ? head.current_revision + 1 : 1,
        kind: "CANVAS",
        parent_revision: head ? head.current_revision : null,
        payload,
        payload_digest: (await digestPayload(payload, this.lineage)) as CanvasRevisionWire["payload_digest"],
        lineage: this.lineage,
        created_by: "default",
        created_at: new Date(0).toISOString(),
      },
      head ? head.head_version : null,
    );
  }
}

class ManualTimers {
  private queue = new Map<number, { run: () => void; ms: number }>();
  private next = 1;

  set = (run: () => void, ms: number) => {
    const id = this.next++;
    this.queue.set(id, { run, ms });
    return id as unknown as ReturnType<typeof setTimeout>;
  };

  clear = (handle: ReturnType<typeof setTimeout>) => {
    this.queue.delete(handle as unknown as number);
  };

  delays(): number[] {
    return [...this.queue.values()].map((timer) => timer.ms);
  }

  /** Fire every pending timer with this delay. */
  fire(ms: number): void {
    for (const [id, timer] of [...this.queue]) {
      if (timer.ms !== ms) continue;
      this.queue.delete(id);
      timer.run();
    }
  }
}

let server: FakeServer;
let timers: ManualTimers;
let persistence: CanvasPersistence;
let ids = 0;

function deps(): PersistenceDeps {
  return {
    client: server,
    t: (key) => key,
    now: () => new Date(1_000),
    newCommandId: () => `cmd-${(ids += 1)}`,
    setTimer: timers.set,
    clearTimer: timers.clear,
  };
}

const store = () => useCanvasStore.getState();
const saveState = () => deriveSaveState(useSaveStatusStore.getState().scopes, canvasSaveScope(PROJECT, CANDIDATE));

async function autosave(): Promise<void> {
  timers.fire(AUTOSAVE_DELAY_MS);
  await vi.waitFor(() => expect(saveState().status).not.toBe("saving"));
  await vi.waitFor(() => expect(saveState().status).not.toBe("idle"));
}

beforeEach(() => {
  window.localStorage.clear();
  useSaveStatusStore.getState().reset();
  store().reset();
  server = new FakeServer();
  timers = new ManualTimers();
  persistence = new CanvasPersistence(deps());
});

describe("opening a Canvas", () => {
  it("opens an unsaved Canvas empty and saves its first edit as the genesis revision", async () => {
    await persistence.openCanvas(PROJECT, 1);
    expect(store().phase).toBe("ready");
    expect(store().graph.nodes).toEqual([]);

    store().edit((graph) => addNode(graph, note("a")));
    await autosave();

    expect(saveState().status).toBe("saved");
    const [saved] = server.revisions.get(CANDIDATE) ?? [];
    expect(saved).toMatchObject({ revision: 1, parent_revision: null, created_by: "default", lineage: server.lineage });
    expect(saved.payload.nodes.map((node) => node.node_id)).toEqual(["a"]);
    expect(readDraft(SCOPE)).toBeNull();
  });

  it("loads the current revision of a saved Canvas", async () => {
    await server.saveElsewhere([note("a")]);
    await server.saveElsewhere([note("a"), note("b")]);

    await persistence.openCanvas(PROJECT, 1);

    expect(server.getCanvasRevision).toHaveBeenCalledWith(PROJECT, CANDIDATE, 2, expect.anything());
    expect(store().graph.nodes.map((node) => node.id)).toEqual(["a", "b"]);
  });

  it("restores a draft edited from the current revision and saves it", async () => {
    await server.saveElsewhere([note("a")]);
    writeDraft(SCOPE, {
      baseRevision: 1,
      nodes: [note("a", "edited offline")],
      edges: [],
      viewport: null,
      metadata: null,
      history: null,
      mutation: { userEditsSinceHydrate: 1, lastMutationSource: "user_edit", pendingClearIntent: false },
      updatedAt: 1,
    });

    await persistence.openCanvas(PROJECT, 1);
    expect(store().graph.nodes[0].data.label).toBe("edited offline");
    await autosave();

    expect(server.heads.get(CANDIDATE)?.current_revision).toBe(2);
  });

  it("keeps a draft from an older revision aside and loads the server content", async () => {
    await server.saveElsewhere([note("a")]);
    await server.saveElsewhere([note("a", "newer")]);
    writeDraft(SCOPE, {
      baseRevision: 1,
      nodes: [note("a", "mine")],
      edges: [],
      viewport: null,
      metadata: null,
      history: null,
      mutation: { userEditsSinceHydrate: 1, lastMutationSource: "user_edit", pendingClearIntent: false },
      updatedAt: 1,
    });

    await persistence.openCanvas(PROJECT, 1);

    expect(store().graph.nodes[0].data.label).toBe("newer");
    expect(store().conflict?.nodes[0].data.label).toBe("mine");
    expect(readConflictSnapshot(SCOPE)).not.toBeNull();
    expect(timers.delays()).toEqual([]);
  });

  it("ignores a load that a later open replaced", async () => {
    let release: () => void = () => undefined;
    server.getExplorationContext.mockImplementationOnce(
      () => new Promise((resolve) => (release = () => resolve({ lineage: server.lineage, created_by: "default" }))),
    );
    const first = persistence.openCanvas(PROJECT, 1);
    await persistence.openCanvas(PROJECT, 2);
    release();
    await first;

    expect(store().phase).toBe("ready");
    expect(server.getCandidateHead).toHaveBeenCalledTimes(1);
    expect(server.getCandidateHead).toHaveBeenCalledWith(PROJECT, "canvas-episode-2", expect.anything());
  });

  it("reports a load failure", async () => {
    server.getExplorationContext.mockRejectedValueOnce(new ApiRequestError("No script for this episode.", undefined, 404));

    await persistence.openCanvas(PROJECT, 1);

    expect(store()).toMatchObject({ phase: "error", loadError: "No script for this episode." });
  });
});

describe("saving", () => {
  beforeEach(async () => {
    await persistence.openCanvas(PROJECT, 1);
  });

  it("binds the lineage current at save time", async () => {
    store().edit((graph) => addNode(graph, note("a")));
    await autosave();
    server.lineage = lineage("9");
    store().edit((graph) => addNode(graph, note("b")));
    await autosave();

    expect(server.revisions.get(CANDIDATE)?.map((revision) => revision.lineage.content_basis_digest)).toEqual([
      DIGEST("1"),
      DIGEST("9"),
    ]);
  });

  it("writes the draft before autosave", () => {
    store().edit((graph) => addNode(graph, note("a")));
    timers.fire(300);

    expect(readDraft(SCOPE)?.nodes.map((node) => node.id)).toEqual(["a"]);
    expect(server.appendCanvasRevision).not.toHaveBeenCalled();
  });

  it("keeps local work aside when another tab saved first, then saves it on request", async () => {
    store().edit((graph) => addNode(graph, note("mine")));
    await server.saveElsewhere([note("theirs")]);

    await autosave();

    expect(saveState().status).toBe("error");
    expect(store().graph.nodes.map((node) => node.id)).toEqual(["theirs"]);
    expect(store().conflict?.nodes.map((node) => node.id)).toEqual(["mine"]);

    persistence.resolveConflict("mine");
    await autosave();

    expect(saveState().status).toBe("saved");
    expect(server.heads.get(CANDIDATE)?.current_revision).toBe(2);
    expect(store().conflict).toBeNull();
    expect(readConflictSnapshot(SCOPE)).toBeNull();
  });

  it("drops local work aside on request and keeps the server content", async () => {
    store().edit((graph) => addNode(graph, note("mine")));
    await server.saveElsewhere([note("theirs")]);
    await autosave();

    persistence.resolveConflict("server");

    expect(store().conflict).toBeNull();
    expect(store().graph.nodes.map((node) => node.id)).toEqual(["theirs"]);
    expect(saveState().status).toBe("idle");
  });

  it("reports a 409 on an unmoved head as an error, not a conflict", async () => {
    server.failNext.push(409);
    store().edit((graph) => addNode(graph, note("a")));

    await autosave();

    expect(saveState()).toMatchObject({ status: "error", error: "The canvas changed elsewhere." });
    expect(store().conflict).toBeNull();
    expect(store().graph.nodes.map((node) => node.id)).toEqual(["a"]);
  });

  it("retries a transient failure", async () => {
    server.failNext.push(503);
    store().edit((graph) => addNode(graph, note("a")));
    await autosave();
    expect(saveState().status).toBe("error");

    timers.fire(RETRY_DELAY_MS);
    await vi.waitFor(() => expect(saveState().status).toBe("saved"));

    expect(server.heads.get(CANDIDATE)?.current_revision).toBe(1);
  });

  it("blocks an emptied Canvas without a clear intent and sends an explicit clear", async () => {
    store().edit((graph) => addNode(graph, note("a")));
    await autosave();
    store().replace({ graph: { ...store().graph, nodes: [] } });
    store().edit((graph) => ({ ...graph, userEditsSinceHydrate: graph.userEditsSinceHydrate + 1 }));
    await autosave();
    expect(saveState()).toMatchObject({ status: "error", error: "creative_canvas_save_dangerous_empty" });

    store().edit((graph) => clearCanvas(addNode(graph, note("b"))));
    await autosave();

    expect(saveState().status).toBe("saved");
    expect(server.revisions.get(CANDIDATE)?.at(-1)?.payload.nodes).toEqual([]);
    expect(store().graph.pendingClearIntent).toBe(false);
  });

  it("stops autosaving after close and keeps the draft", () => {
    store().edit((graph) => addNode(graph, note("a")));
    persistence.close();

    expect(timers.delays()).toEqual([]);
    expect(readDraft(SCOPE)?.nodes.map((node) => node.id)).toEqual(["a"]);
  });
});

describe("kept-aside work and late responses", () => {
  const draftFrom = (baseRevision: number, label: string) => ({
    baseRevision,
    nodes: [note("a", label)],
    edges: [],
    viewport: null,
    metadata: null,
    history: null,
    mutation: { userEditsSinceHydrate: 1, lastMutationSource: "user_edit" as const, pendingClearIntent: false },
    // Fresh: the storage reclaimers that run on a full quota prune drafts past their TTL.
    updatedAt: Date.now(),
  });

  it("offers kept-aside work again when the Canvas is reopened", async () => {
    await server.saveElsewhere([note("a")]);
    await server.saveElsewhere([note("a", "newer")]);
    writeDraft(SCOPE, draftFrom(1, "mine"));
    await persistence.openCanvas(PROJECT, 1);
    persistence.close();

    await persistence.openCanvas(PROJECT, 1);

    expect(store().conflict?.nodes[0].data.label).toBe("mine");
  });

  it("keeps both an older kept-aside version and a newer conflicting draft", async () => {
    await server.saveElsewhere([note("a")]);
    await server.saveElsewhere([note("a", "newer")]);
    writeConflictSnapshot(SCOPE, {
      nodes: [note("a", "older")],
      edges: [],
      viewport: null,
      metadata: null,
      timestamp: new Date(0).toISOString(),
    });
    writeDraft(SCOPE, draftFrom(1, "mine"));

    await persistence.openCanvas(PROJECT, 1);

    expect(store().conflict?.nodes[0].data.label).toBe("older");
    expect(readDraft(SCOPE)?.nodes[0].data.label).toBe("mine");
  });

  it("does not keep another Canvas's graph aside when the user switches during a 409", async () => {
    await persistence.openCanvas(PROJECT, 1);
    store().edit((graph) => addNode(graph, note("mine")));
    await server.saveElsewhere([note("theirs")]);
    let releaseHead: () => void = () => undefined;
    const original = server.getCandidateHead.getMockImplementation();
    let calls = 0;
    server.getCandidateHead.mockImplementation((project: string, id: string) => {
      calls += 1;
      if (calls === 1) {
        return new Promise((resolve, reject) => {
          releaseHead = () => void original?.(project, id).then(resolve, reject);
        });
      }
      return original?.(project, id) ?? Promise.reject(new Error("no head"));
    });

    timers.fire(AUTOSAVE_DELAY_MS);
    await vi.waitFor(() => expect(calls).toBe(1));
    await persistence.openCanvas(PROJECT, 2);
    store().edit((graph) => addNode(graph, note("episode-2")));
    releaseHead();
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(readConflictSnapshot(SCOPE)).toBeNull();
    expect(readDraft(SCOPE)?.nodes.map((node) => node.id)).toEqual(["mine"]);
    expect(store().graph.nodes.map((node) => node.id)).toEqual(["episode-2"]);
  });

  it("keeps the draft of an edit made while a save was in flight", async () => {
    await persistence.openCanvas(PROJECT, 1);
    let release: () => void = () => undefined;
    const original = server.appendCanvasRevision.getMockImplementation();
    server.appendCanvasRevision.mockImplementationOnce(
      (...args: Parameters<FakeServer["appendCanvasRevision"]>) =>
        new Promise((resolve, reject) => {
          release = () => void original?.(...args).then(resolve, reject);
        }),
    );
    store().edit((graph) => addNode(graph, note("a")));
    timers.fire(AUTOSAVE_DELAY_MS);
    await vi.waitFor(() => expect(server.appendCanvasRevision).toHaveBeenCalledTimes(1));

    store().edit((graph) => addNode(graph, note("b")));
    timers.fire(300);
    release();
    await vi.waitFor(() => expect(saveState().status).toBe("saved"));

    expect(readDraft(SCOPE)?.nodes.map((node) => node.id)).toEqual(["a", "b"]);
  });

  it("settles two kept-aside versions one after the other without losing either", async () => {
    await server.saveElsewhere([note("a")]);
    await server.saveElsewhere([note("a", "newer")]);
    writeConflictSnapshot(SCOPE, {
      nodes: [note("a", "older")],
      edges: [],
      viewport: null,
      metadata: null,
      timestamp: new Date(0).toISOString(),
    });
    writeDraft(SCOPE, draftFrom(1, "mine"));
    await persistence.openCanvas(PROJECT, 1);

    persistence.resolveConflict("mine");
    timers.fire(300);

    expect(store().graph.nodes[0].data.label).toBe("older");
    expect(store().conflict?.nodes[0].data.label).toBe("mine");
    expect(readConflictSnapshot(SCOPE)?.nodes[0].data.label).toBe("mine");

    persistence.close();
    await persistence.openCanvas(PROJECT, 1);
    expect(store().conflict?.nodes[0].data.label).toBe("mine");

    persistence.resolveConflict("mine");
    await autosave();

    expect(store().conflict).toBeNull();
    expect(server.revisions.get(CANDIDATE)?.at(-1)?.payload.nodes[0].body.data).toMatchObject({ label: "mine" });
  });

  it("keeps a waiting draft when the Canvas closes during a stacked conflict", async () => {
    await server.saveElsewhere([note("a")]);
    await server.saveElsewhere([note("a", "newer")]);
    writeConflictSnapshot(SCOPE, {
      nodes: [note("a", "older")],
      edges: [],
      viewport: null,
      metadata: null,
      timestamp: new Date(0).toISOString(),
    });
    writeDraft(SCOPE, draftFrom(1, "mine"));
    await persistence.openCanvas(PROJECT, 1);

    store().edit((graph) => addNode(graph, note("while-deciding")));
    timers.fire(300);
    persistence.close();

    expect(readDraft(SCOPE)?.nodes[0].data.label).toBe("mine");
  });

  it("refuses edits while kept-aside work waits for the user", async () => {
    await server.saveElsewhere([note("a")]);
    await server.saveElsewhere([note("a", "newer")]);
    writeDraft(SCOPE, draftFrom(1, "mine"));
    await persistence.openCanvas(PROJECT, 1);
    const before = store().graph;

    store().edit((graph) => addNode(graph, note("ignored")));

    expect(store().graph).toBe(before);
    expect(store().editSeq).toBe(0);
  });

  it("keeps a conflicting draft in its slot when the kept-aside slot cannot be written", async () => {
    await server.saveElsewhere([note("a")]);
    await server.saveElsewhere([note("a", "newer")]);
    writeDraft(SCOPE, draftFrom(1, "mine"));
    const originalSetItem = Storage.prototype.setItem;
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key, value) {
      if (key.startsWith("arcreel:creative-canvas:conflict:")) throw new DOMException("full", "QuotaExceededError");
      originalSetItem.call(this, key, value);
    });

    await persistence.openCanvas(PROJECT, 1);
    timers.fire(300);
    persistence.close();

    expect(store().conflict?.nodes[0].data.label).toBe("mine");
    expect(readDraft(SCOPE)?.nodes[0].data.label).toBe("mine");
    spy.mockRestore();
  });

  it("keeps the waiting draft when it cannot move into the kept-aside slot", async () => {
    await server.saveElsewhere([note("a")]);
    await server.saveElsewhere([note("a", "newer")]);
    writeConflictSnapshot(SCOPE, {
      nodes: [note("a", "older")],
      edges: [],
      viewport: null,
      metadata: null,
      timestamp: new Date(0).toISOString(),
    });
    writeDraft(SCOPE, draftFrom(1, "mine"));
    await persistence.openCanvas(PROJECT, 1);
    const originalSetItem = Storage.prototype.setItem;
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key, value) {
      if (key.startsWith("arcreel:creative-canvas:conflict:")) throw new DOMException("full", "QuotaExceededError");
      originalSetItem.call(this, key, value);
    });

    persistence.resolveConflict("mine");
    timers.fire(300);
    persistence.close();

    expect(store().conflict?.nodes[0].data.label).toBe("mine");
    expect(readDraft(SCOPE)?.nodes[0].data.label).toBe("mine");
    spy.mockRestore();
    await persistence.openCanvas(PROJECT, 1);
    expect(store().conflict?.nodes[0].data.label).toBe("mine");
  });
});

