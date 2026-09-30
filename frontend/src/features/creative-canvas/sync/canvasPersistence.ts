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
 * device moved it, the local work is kept aside (`keptAside.ts`) and the
 * server content is loaded. While any version is kept aside the Canvas is
 * read-only, and the user settles the versions one by one, oldest first:
 * "mine" applies a version on top of the server content, "server" drops it.
 * Nothing is overwritten automatically. A 409 on an unmoved head is reported
 * as an error.
 *
 * The draft slot only ever holds the work on screen; kept-aside versions have
 * their own keys, or live in memory when storage refuses them.
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
  clearDraft,
  decideDraftRecovery,
  readDraft,
  writeDraft,
  type ConflictSnapshot,
  type DraftScope,
  type StoredDraft,
} from "../recovery/draftRecovery";
import { keepAside, readKeptAside, settleKeptAside, type KeptAsideVersion } from "../recovery/keptAside";
import {
  checkPayloadLimits,
  classifySaveOutcome,
  decideSaveAction,
  describePayloadViolation,
  type Translate,
} from "../recovery/saveDecision";
import { createCanvasSaveSession, type CanvasSaveSession } from "../recovery/saveCoordinator";
import { setUnstoredWork } from "../recovery/unloadGuard";
import { useCanvasStore, type CanvasStoreState } from "../state/canvasStore";
import { flushPendingFieldEdits } from "../state/pendingFieldEdits";
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
  /** The kept-aside version shown to the user, the oldest one. */
  shown: KeptAsideVersion | null;
  /** Whether the graph on screen is the server's content; both choices need it first. */
  serverShown: boolean;
  /** A "mine" choice not saved yet because more versions waited; saved once none is left. */
  unsavedResolution: boolean;
  /** `editSeq` when the screen last matched the server (loaded, saved or reloaded); null if it never did. */
  cleanEditSeq: number | null;
  /** The server reload in flight; choices wait for it instead of starting another. */
  reloading: Promise<void> | null;
  /** Bumped by every reload and by every choice; a reload applies only if nothing moved since it began. */
  screenSeq: number;
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
      // A conflicting draft is kept aside; so is any draft while older versions wait, so that a
      // choice about an older version can never replace it silently.
      const waiting = readKeptAside(draftScope).length > 0;
      if (decision.kind === "conflict" || (decision.kind === "draft" && waiting)) {
        const version = keepAside(draftScope, snapshotOf(decision.draft));
        if (version.key) clearDraft(draftScope);
      }
      const queue = readKeptAside(draftScope);
      const state = this.store.getState();
      const hydrate = decision.kind === "draft" && queue.length === 0;
      if (hydrate) {
        state.replace({
          graph: hydrateDraft(state.graph, decision.draft),
          bookmarks: bookmarksOf(decision.draft.metadata),
        });
      } else {
        state.replace({ graph: loadGraph(state.graph, remote.nodes, remote.edges), bookmarks: remote.bookmarks });
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
        session: createCanvasSaveSession({
          canvasKey: `${projectName}:${candidateId}`,
          generation,
          runSave: (version, session) => this.runSave(version, session),
        }),
        shown: null,
        serverShown: !hydrate,
        unsavedResolution: false,
        cleanEditSeq: hydrate ? null : this.store.getState().editSeq,
        reloading: null,
        screenSeq: 0,
      };
      writeSaveStatus(saveScope, "idle");
      this.store.getState().replace({ phase: "ready" });
      this.showNext(this.open);
      this.watchEdits(projectName);
      if (hydrate) this.scheduleAutosave();
    } catch (error) {
      if (signal.aborted || isAbort(error)) return;
      const message = error instanceof Error && error.message ? error.message : this.deps.t("creative_canvas_load_failed");
      this.store.getState().replace({ phase: "error", loadError: message });
    } finally {
      if (this.loading === loading) this.loading = null;
    }
  }

  /**
   * Leave the Canvas. The work on screen goes to the draft; when storage refuses it, it is
   * kept aside in memory and offered again when the Canvas reopens. An append already on the
   * wire is left to finish.
   */
  close(): void {
    this.loading?.abort();
    this.loading = null;
    for (const unsubscribe of this.unsubscribers) unsubscribe();
    this.unsubscribers = [];
    for (const timer of [this.autosaveTimer, this.draftTimer, this.retryTimer]) {
      if (timer !== null) this.deps.clearTimer(timer);
    }
    this.autosaveTimer = this.draftTimer = this.retryTimer = null;
    const open = this.open;
    if (open) {
      flushPendingFieldEdits();
      const unsaved = this.store.getState().editSeq !== open.cleanEditSeq;
      if (unsaved && !this.writeDraftNow(open)) {
        keepAside(open.draftScope, this.localSnapshot());
        // The kept-aside copy, stored or guarded in memory, now carries this work.
        this.markUnstored(open, false);
      }
      open.session.dispose();
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
   * Settle the shown kept-aside version. `"server"` drops it; `"mine"` applies it on top of the
   * server content as one undoable edit. Both first make sure the server content is on screen;
   * if it cannot be loaded, the version stays shown and nothing changes.
   */
  resolveConflict(choice: "server" | "mine"): Promise<void> {
    const open = this.open;
    if (!open?.shown) return Promise.resolve();
    return this.settle(open, open.shown, choice);
  }

  private async settle(open: OpenCanvas, version: KeptAsideVersion, choice: "server" | "mine"): Promise<void> {
    if (!open.serverShown) {
      await (open.reloading ?? this.reloadServer(open));
      if (this.open !== open || open.shown !== version) return;
      if (!open.serverShown) {
        this.fail(open, this.deps.t("creative_canvas_load_failed"));
        return;
      }
    }
    settleKeptAside(open.draftScope, version);
    open.shown = null;
    // No reload that began before this choice may replace its result.
    open.screenSeq += 1;
    // Edits are refused while a version is shown: clear it, apply the choice, then show the next.
    this.store.getState().replace({ conflict: null, conflictMode: "kept" });
    if (choice === "mine") {
      const { snapshot } = version;
      this.store.getState().edit((graph) => commitEdit(graph, snapshot.nodes, snapshot.edges));
      if (snapshot.metadata) this.store.getState().editBookmarks(() => bookmarksOf(snapshot.metadata));
      open.unsavedResolution = true;
    }
    if (this.showNext(open)) return;
    if (open.unsavedResolution) {
      open.unsavedResolution = false;
      this.scheduleAutosave();
    } else {
      writeSaveStatus(open.saveScope, "idle");
    }
  }

  /** Show the oldest kept-aside version, if any; true when one is shown. */
  private showNext(open: OpenCanvas): boolean {
    const [next] = readKeptAside(open.draftScope);
    open.shown = next ?? null;
    this.store
      .getState()
      .replace({ conflict: next?.snapshot ?? null, conflictMode: next && !next.key ? "unkept" : "kept" });
    return next !== undefined;
  }

  private localSnapshot(): ConflictSnapshot {
    const { graph, bookmarks } = this.store.getState();
    return {
      nodes: [...graph.nodes],
      edges: [...graph.edges],
      viewport: null,
      metadata: metadataOf(bookmarks),
      timestamp: this.deps.now().toISOString(),
    };
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

  /**
   * Write the work on screen to the draft; false when storage refused it. Unsaved work the draft
   * could not hold keeps the unload guard on until a save lands.
   */
  private writeDraftNow(open: OpenCanvas): boolean {
    const { graph, bookmarks, editSeq } = this.store.getState();
    const written = writeDraft(open.draftScope, {
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
    this.markUnstored(open, !written && editSeq !== open.cleanEditSeq);
    return written;
  }

  private markUnstored(open: OpenCanvas, unstored: boolean): void {
    setUnstoredWork(`draft:${open.saveScope}`, unstored);
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
      open.cleanEditSeq = editSeq;
      this.markUnstored(open, false);
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

  /**
   * Load the server's current revision onto the screen. On failure the graph on screen is
   * kept and `serverShown` is false, so a later choice loads it again.
   */
  private reloadServer(open: OpenCanvas): Promise<void> {
    open.screenSeq += 1;
    const seq = open.screenSeq;
    const run = (async () => {
      try {
        const head = await this.readHead(open.projectName, open.candidateId);
        const remote = head
          ? fromCanvasPayload(
              (await this.deps.client.getCanvasRevision(open.projectName, open.candidateId, head.current_revision)).payload,
            )
          : EMPTY;
        // A later reload or a choice made meanwhile owns the screen now.
        if (this.open !== open || open.screenSeq !== seq) return;
        open.head = head;
        open.lastRemoteNodeCount = remote.nodes.length;
        open.serverShown = true;
        const state = this.store.getState();
        state.replace({ graph: loadGraph(state.graph, remote.nodes, remote.edges), bookmarks: remote.bookmarks });
        open.cleanEditSeq = this.store.getState().editSeq;
      } catch {
        if (this.open === open && open.screenSeq === seq) open.serverShown = false;
      }
    })();
    const tracked = run.finally(() => {
      if (open.reloading === tracked) open.reloading = null;
    });
    open.reloading = tracked;
    return tracked;
  }

  /** After a 409 on a moved head: keep the local work aside, then load the server content. */
  private async keepAsideAndReload(open: OpenCanvas, message: string): Promise<false> {
    flushPendingFieldEdits();
    const version = keepAside(open.draftScope, this.localSnapshot());
    // Stored under its own key, the draft copy is redundant; held in memory, the draft stays too.
    if (version.key) clearDraft(open.draftScope);
    this.showNext(open);
    open.serverShown = false;
    await this.reloadServer(open);
    return this.fail(open, message);
  }
}
