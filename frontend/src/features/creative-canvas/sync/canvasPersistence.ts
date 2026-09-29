/**
 * Load and save of one episode Canvas through the M8 exploration API.
 *
 * Opening reads the server context (lineage and author, ADR-0098), the
 * candidate head and its current revision, then decides against the local
 * draft (`decideDraftRecovery`). Every user edit writes the local draft soon
 * and autosaves later through one save session (`createCanvasSaveSession`):
 * at most one append in flight, edits during it coalesced into one follow-up.
 *
 * Each save rereads the context, so a revision binds the lineage current when
 * it is saved. A 409 is resolved by rereading the head: when another tab or
 * device moved it, the local content is kept aside as a conflict snapshot, the
 * server content is loaded, and autosave stops until the user decides. Nothing
 * is overwritten automatically. A 409 on an unmoved head is reported as an
 * error.
 */

import { ApiRequestError } from "@/api";

import {
  appendCanvasRevision,
  buildCanvasRevision,
  canvasCandidateId,
  getCandidateHead,
  getCanvasRevision,
  getExplorationContext,
} from "../api/explorationClient";
import { fromCanvasPayload, toCanvasPayload, type LoadedCanvas } from "../api/serialize";
import type { CandidateHead, ExplorationContext } from "../api/types";
import { createEmptyBookmarks, type ViewportBookmarks } from "../domain/bookmarks";
import { acknowledgeClear, commitEdit, hydrateDraft, loadGraph } from "../domain/graph";
import { isCanvasAutosaveHeld, subscribeCanvasAutosaveRelease } from "../recovery/autosaveHold";
import {
  clearConflictSnapshot,
  clearDraft,
  decideDraftRecovery,
  readConflictSnapshot,
  readDraft,
  writeConflictSnapshot,
  writeDraft,
  type ConflictSnapshot,
  type DraftScope,
  type StoredDraft,
} from "../recovery/draftRecovery";
import {
  checkPayloadLimits,
  classifySaveOutcome,
  decideSaveAction,
  describePayloadViolation,
  type Translate,
} from "../recovery/saveDecision";
import { createCanvasSaveSession, type CanvasSaveSession } from "../recovery/saveCoordinator";
import { useCanvasStore, type CanvasStoreState } from "../state/canvasStore";
import { canvasSaveScope, writeSaveStatus } from "../state/saveStatusStore";

export const AUTOSAVE_DELAY_MS = 1_200;
export const DRAFT_DELAY_MS = 300;
export const RETRY_DELAY_MS = 5_000;

export interface ExplorationClient {
  getExplorationContext: typeof getExplorationContext;
  getCandidateHead: typeof getCandidateHead;
  getCanvasRevision: typeof getCanvasRevision;
  appendCanvasRevision: typeof appendCanvasRevision;
}

export interface PersistenceDeps {
  client: ExplorationClient;
  t: Translate;
  now: () => Date;
  newCommandId: () => string;
  setTimer: (run: () => void, ms: number) => ReturnType<typeof setTimeout>;
  clearTimer: (handle: ReturnType<typeof setTimeout>) => void;
}

export const defaultPersistenceDeps = (t: Translate): PersistenceDeps => ({
  client: { getExplorationContext, getCandidateHead, getCanvasRevision, appendCanvasRevision },
  t,
  now: () => new Date(),
  newCommandId: () => crypto.randomUUID(),
  setTimer: (run, ms) => setTimeout(run, ms),
  clearTimer: (handle) => clearTimeout(handle),
});

type Store = typeof useCanvasStore;

interface OpenCanvas {
  projectName: string;
  episode: number;
  candidateId: string;
  saveScope: string;
  draftScope: DraftScope;
  context: ExplorationContext;
  head: CandidateHead | null;
  lastRemoteNodeCount: number;
  session: CanvasSaveSession;
  /**
   * A conflicting draft waits in the draft slot behind an older kept-aside version. It is
   * moved into the kept-aside slot as soon as that version is settled, before any edit can
   * write the draft slot.
   */
  pendingConflictDraft: boolean;
  /** Where the durable copy of the shown conflict lives: its own slot, or (when that write failed) the draft slot. */
  conflictCopy: "snapshot" | "draft" | null;
}

function snapshotOf(draft: StoredDraft): ConflictSnapshot {
  return {
    nodes: draft.nodes,
    edges: draft.edges,
    viewport: draft.viewport,
    metadata: draft.metadata,
    timestamp: new Date(draft.updatedAt).toISOString(),
  };
}

function metadataOf(bookmarks: ViewportBookmarks): Record<string, unknown> {
  return { viewportBookmarks: bookmarks };
}

function bookmarksOf(metadata: Record<string, unknown> | null): ViewportBookmarks {
  const value = metadata?.viewportBookmarks;
  return Array.isArray(value) ? (value as ViewportBookmarks) : createEmptyBookmarks();
}

function statusOf(error: unknown): number | null {
  return error instanceof ApiRequestError ? (error.status ?? null) : null;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

const EMPTY: LoadedCanvas = { nodes: [], edges: [], bookmarks: createEmptyBookmarks() };

export class CanvasPersistence {
  private open: OpenCanvas | null = null;
  private loading: AbortController | null = null;
  private generation = 0;
  private autosaveTimer: ReturnType<typeof setTimeout> | null = null;
  private draftTimer: ReturnType<typeof setTimeout> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private unsubscribers: (() => void)[] = [];

  constructor(
    private readonly deps: PersistenceDeps,
    private readonly store: Store = useCanvasStore,
  ) {}

  /** Load the episode's Canvas; a later `openCanvas` or `close` abandons this one. */
  async openCanvas(projectName: string, episode: number): Promise<void> {
    this.close();
    const loading = new AbortController();
    this.loading = loading;
    const generation = (this.generation += 1);
    const { signal } = loading;
    this.store.getState().reset();
    this.store.getState().replace({ phase: "loading" });
    try {
      const candidateId = canvasCandidateId(episode);
      const context = await this.deps.client.getExplorationContext(projectName, episode, { signal });
      signal.throwIfAborted();
      const head = await this.readHead(projectName, candidateId, signal);
      signal.throwIfAborted();
      const remote = head
        ? fromCanvasPayload(
            (await this.deps.client.getCanvasRevision(projectName, candidateId, head.current_revision, { signal }))
              .payload,
          )
        : EMPTY;
      if (signal.aborted) return;

      const draftScope: DraftScope = { userId: context.created_by, projectName, candidateId };
      const draft = readDraft(draftScope);
      const decision = decideDraftRecovery(
        draft,
        head?.current_revision ?? null,
        remote.nodes,
        remote.edges,
        metadataOf(remote.bookmarks),
      );
      const state = this.store.getState();
      // Work kept aside earlier stays reachable until the user settles it.
      const keptAside = readConflictSnapshot(draftScope);
      let conflict: ConflictSnapshot | null = keptAside;
      let conflictCopy: OpenCanvas["conflictCopy"] = keptAside ? "snapshot" : null;
      if (decision.kind === "draft") {
        state.replace({
          graph: hydrateDraft(state.graph, decision.draft),
          bookmarks: bookmarksOf(decision.draft.metadata),
        });
      } else {
        state.replace({ graph: loadGraph(state.graph, remote.nodes, remote.edges), bookmarks: remote.bookmarks });
        if (decision.kind === "conflict" && !keptAside) {
          conflict = snapshotOf(decision.draft);
          // The draft is the only copy until the kept-aside slot holds it.
          if (writeConflictSnapshot(draftScope, conflict)) {
            clearDraft(draftScope);
            conflictCopy = "snapshot";
          } else {
            conflictCopy = "draft";
          }
        }
      }
      const saveScope = canvasSaveScope(projectName, candidateId);
      this.open = {
        projectName,
        episode,
        candidateId,
        saveScope,
        draftScope,
        context,
        head,
        lastRemoteNodeCount: remote.nodes.length,
        pendingConflictDraft: decision.kind === "conflict" && keptAside !== null,
        conflictCopy,
        session: createCanvasSaveSession({
          canvasKey: `${projectName}:${candidateId}`,
          generation,
          runSave: (version, session) => this.runSave(version, session),
        }),
      };
      writeSaveStatus(saveScope, "idle");
      this.store.getState().replace({ phase: "ready", conflict });
      this.watchEdits(projectName);
      if (decision.kind === "draft") this.scheduleAutosave();
    } catch (error) {
      if (signal.aborted || isAbort(error)) return;
      const message = error instanceof Error && error.message ? error.message : this.deps.t("creative_canvas_load_failed");
      this.store.getState().replace({ phase: "error", loadError: message });
    } finally {
      if (this.loading === loading) this.loading = null;
    }
  }

  /** Leave the Canvas. The local draft stays; an append already on the wire is left to finish. */
  close(): void {
    this.loading?.abort();
    this.loading = null;
    for (const unsubscribe of this.unsubscribers) unsubscribe();
    this.unsubscribers = [];
    for (const timer of [this.autosaveTimer, this.draftTimer, this.retryTimer]) {
      if (timer !== null) this.deps.clearTimer(timer);
    }
    this.autosaveTimer = this.draftTimer = this.retryTimer = null;
    if (this.open) {
      if (this.store.getState().editSeq > 0) this.writeDraftNow(this.open);
      this.open.session.dispose();
    }
    this.open = null;
  }

  /** Save now (the manual save action). Resolves true once the current content is on the server. */
  saveNow(): Promise<boolean> {
    if (!this.open) return Promise.resolve(false);
    this.cancelAutosave();
    this.writeDraftNow(this.open);
    return this.open.session.requestSave();
  }

  /**
   * Settle a conflict. `"server"` drops the kept-aside local content. `"mine"`
   * puts it back on top of the server content as one undoable edit and saves it.
   */
  resolveConflict(choice: "server" | "mine"): void {
    const open = this.open;
    const conflict = this.store.getState().conflict;
    if (!open || !conflict) return;
    const settledCopy = open.conflictCopy;
    // The next kept-aside version, if a conflicting draft waited behind this one.
    const waiting = open.pendingConflictDraft ? readDraft(open.draftScope) : null;
    let next: ConflictSnapshot | null = null;
    let nextCopy: OpenCanvas["conflictCopy"] = null;
    if (waiting) {
      next = snapshotOf(waiting);
      // Replace the settled version in its slot; if that fails, free the slot and retry once.
      let moved = writeConflictSnapshot(open.draftScope, next);
      if (!moved) {
        clearConflictSnapshot(open.draftScope);
        moved = writeConflictSnapshot(open.draftScope, next);
      }
      if (moved) clearDraft(open.draftScope);
      nextCopy = moved ? "snapshot" : "draft";
    } else if (settledCopy === "snapshot") {
      clearConflictSnapshot(open.draftScope);
    } else if (settledCopy === "draft" && choice === "server") {
      clearDraft(open.draftScope);
    }
    open.pendingConflictDraft = false;
    open.conflictCopy = null;
    // Edits are refused while a conflict is shown: settle the choice first, then show the next one.
    this.store.getState().replace({ conflict: null });
    if (choice === "mine") {
      this.store.getState().edit((graph) => commitEdit(graph, conflict.nodes, conflict.edges));
      if (conflict.metadata) this.store.getState().editBookmarks(() => bookmarksOf(conflict.metadata));
    }
    if (next) {
      open.conflictCopy = nextCopy;
      this.store.getState().replace({ conflict: next });
    } else if (choice === "server") {
      writeSaveStatus(open.saveScope, "idle");
    }
  }

  private async readHead(projectName: string, candidateId: string, signal?: AbortSignal): Promise<CandidateHead | null> {
    try {
      return await this.deps.client.getCandidateHead(projectName, candidateId, { signal });
    } catch (error) {
      if (statusOf(error) === 404) return null;
      throw error;
    }
  }

  private watchEdits(projectName: string): void {
    this.unsubscribers.push(
      this.store.subscribe((state: CanvasStoreState, previous: CanvasStoreState) => {
        if (state.editSeq === previous.editSeq || !this.open) return;
        this.scheduleDraft();
        this.scheduleAutosave();
      }),
      subscribeCanvasAutosaveRelease((released) => {
        if (released === projectName && this.open && this.store.getState().editSeq > 0) this.scheduleAutosave();
      }),
    );
  }

  private scheduleDraft(): void {
    if (this.draftTimer !== null) this.deps.clearTimer(this.draftTimer);
    this.draftTimer = this.deps.setTimer(() => {
      this.draftTimer = null;
      if (this.open) this.writeDraftNow(this.open);
    }, DRAFT_DELAY_MS);
  }

  private writeDraftNow(open: OpenCanvas): void {
    // The draft slot may hold the only copy of kept-aside work: a draft waiting behind a kept-aside
    // version, or the shown conflict itself when its own slot could not be written. Never overwrite it.
    if (open.pendingConflictDraft || open.conflictCopy === "draft") return;
    const { graph, bookmarks } = this.store.getState();
    writeDraft(open.draftScope, {
      baseRevision: open.head?.current_revision ?? null,
      nodes: [...graph.nodes],
      edges: [...graph.edges],
      viewport: null,
      metadata: metadataOf(bookmarks),
      history: graph.history,
      mutation: {
        userEditsSinceHydrate: graph.userEditsSinceHydrate,
        lastMutationSource: graph.lastMutationSource,
        pendingClearIntent: graph.pendingClearIntent,
      },
      updatedAt: this.deps.now().getTime(),
    });
  }

  private cancelAutosave(): void {
    if (this.autosaveTimer !== null) this.deps.clearTimer(this.autosaveTimer);
    this.autosaveTimer = null;
  }

  private scheduleAutosave(delay = AUTOSAVE_DELAY_MS): void {
    const open = this.open;
    if (!open || this.store.getState().conflict || isCanvasAutosaveHeld(open.projectName)) return;
    this.cancelAutosave();
    this.autosaveTimer = this.deps.setTimer(() => {
      this.autosaveTimer = null;
      if (this.open === open) void open.session.requestSave();
    }, delay);
  }

  private fail(open: OpenCanvas, message: string): false {
    writeSaveStatus(open.saveScope, "error", message);
    return false;
  }

  private async runSave(version: number, session: CanvasSaveSession): Promise<boolean> {
    const open = this.open;
    if (!open || open.session !== session) return false;
    const { t } = this.deps;
    const { graph, bookmarks, phase, conflict, editSeq } = this.store.getState();
    if (conflict) return false;
    const decision = decideSaveAction({
      hydrated: phase === "ready",
      switching: false,
      nodeCount: graph.nodes.length,
      edgeCount: graph.edges.length,
      lastRemoteNodeCount: open.lastRemoteNodeCount,
      userEditsSinceHydrate: graph.userEditsSinceHydrate,
      lastMutationSource: graph.lastMutationSource,
      pendingClearIntent: graph.pendingClearIntent,
    });
    if (decision.kind === "skip") return false;
    if (decision.kind === "block") return this.fail(open, t("creative_canvas_save_dangerous_empty"));
    const violation = checkPayloadLimits(graph.nodes.length, graph.edges.length, null);
    if (violation) return this.fail(open, describePayloadViolation(violation, t));

    const payload = toCanvasPayload(graph.nodes, graph.edges, bookmarks);
    writeSaveStatus(open.saveScope, "saving");
    const commandId = this.deps.newCommandId();
    let head: CandidateHead;
    try {
      // Every revision binds the lineage current when it is saved (ADR-0098).
      open.context = await this.deps.client.getExplorationContext(open.projectName, open.episode);
      const revision = await buildCanvasRevision({
        projectName: open.projectName,
        candidateId: open.candidateId,
        context: open.context,
        payload,
        head: open.head,
        commandId,
        now: this.deps.now(),
      });
      head = await this.deps.client.appendCanvasRevision(
        open.projectName,
        revision,
        open.head?.head_version ?? null,
        commandId,
      );
    } catch (error) {
      if (this.open !== open) return false;
      const outcome = classifySaveOutcome(
        statusOf(error),
        { detail: error instanceof Error ? error.message : undefined },
        t("creative_canvas_save_failed"),
      );
      if (outcome.kind === "conflict" && (await this.headMoved(open))) {
        return this.open === open ? this.keepAsideAndReload(open, outcome.message) : false;
      }
      if (outcome.kind === "retry") {
        this.retryTimer = this.deps.setTimer(() => {
          this.retryTimer = null;
          if (this.open === open) void open.session.requestSave();
        }, RETRY_DELAY_MS);
      }
      return this.fail(open, outcome.message);
    }
    if (this.open !== open) return true;
    open.head = head;
    open.lastRemoteNodeCount = graph.nodes.length;
    if (graph.lastMutationSource === "manual_clear" || graph.pendingClearIntent) {
      const current = this.store.getState().graph;
      this.store.getState().replace({ graph: acknowledgeClear(current) });
    }
    // The draft is the only copy of edits made after this save read the graph: keep it then.
    if (this.store.getState().editSeq === editSeq && !session.hasUnsavedContentBeyond(version)) {
      clearDraft(open.draftScope);
    }
    writeSaveStatus(open.saveScope, "saved");
    return true;
  }

  /** After a 409: whether the server head differs from the one this save started from. */
  private async headMoved(open: OpenCanvas): Promise<boolean> {
    try {
      const head = await this.readHead(open.projectName, open.candidateId);
      if (head === null || open.head === null) return head !== open.head;
      return head.current_revision !== open.head.current_revision || head.head_version !== open.head.head_version;
    } catch {
      return false;
    }
  }

  /** Load the server's current revision and show `conflict` as kept-aside work. */
  private async reloadServer(open: OpenCanvas, conflict: ConflictSnapshot): Promise<void> {
    try {
      const head = await this.readHead(open.projectName, open.candidateId);
      const remote = head
        ? fromCanvasPayload(
            (await this.deps.client.getCanvasRevision(open.projectName, open.candidateId, head.current_revision)).payload,
          )
        : EMPTY;
      if (this.open !== open) return;
      open.head = head;
      open.lastRemoteNodeCount = remote.nodes.length;
      const state = this.store.getState();
      state.replace({
        graph: loadGraph(state.graph, remote.nodes, remote.edges),
        bookmarks: remote.bookmarks,
        conflict,
      });
    } catch {
      if (this.open === open) this.store.getState().replace({ conflict });
    }
  }

  private async keepAsideAndReload(open: OpenCanvas, message: string): Promise<false> {
    const taken = readConflictSnapshot(open.draftScope);
    if (taken) {
      // The kept-aside slot is taken: the local work waits in the draft behind that version.
      this.writeDraftNow(open);
      open.pendingConflictDraft = true;
      open.conflictCopy = "snapshot";
      await this.reloadServer(open, taken);
      return this.fail(open, message);
    }
    const { graph, bookmarks } = this.store.getState();
    const conflict: ConflictSnapshot = {
      nodes: [...graph.nodes],
      edges: [...graph.edges],
      viewport: null,
      metadata: metadataOf(bookmarks),
      timestamp: this.deps.now().toISOString(),
    };
    if (writeConflictSnapshot(open.draftScope, conflict)) {
      clearDraft(open.draftScope);
      open.conflictCopy = "snapshot";
    } else {
      // The kept-aside slot cannot be written: the local work stays in the draft slot.
      this.writeDraftNow(open);
      open.conflictCopy = "draft";
    }
    await this.reloadServer(open, conflict);
    return this.fail(open, message);
  }
}
