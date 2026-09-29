/**
 * Shared scenario runner of the M8-B save and recovery parity harness.
 *
 * It imports nothing: the donor side (recovery.parity.test.ts, run inside the
 * pinned DramaClaw checkout) and the port side
 * (frontend/src/features/creative-canvas/__parity__/recovery.parity.test.ts)
 * pass their own implementations, so both sides run the same scenario code on
 * the same fixtures.
 */

export interface SaveSessionLike {
  isDisposed(): boolean;
  isSaving(): boolean;
  contentVersion(): number;
  savedVersion(): number;
  hasUnsavedContentBeyond(version: number): boolean;
  requestSave(): Promise<boolean>;
  dispose(): void;
}

export interface DraftScopeLike {
  user: string;
  project: string;
  canvas: string;
}

export interface DraftLike {
  baseRevision: number | null;
  nodes: unknown[];
  history: unknown;
  mutation: unknown;
  updatedAt: number;
}

export interface RecoveryImpl {
  createSession(canvasKey: string, generation: number, runSave: (version: number) => Promise<boolean>): SaveSessionLike;
  decideSaveAction(snapshot: Record<string, unknown>): unknown;
  checkPayloadLimits(nodes: number, edges: number, size: number | null): unknown;
  /** The save-failure classification; returns its kind. */
  classifySave(status: number | null, detail: string | undefined): string;
  setSaveStatus(scope: string, status: string, error?: string): void;
  deriveSaveStatus(scope: string): unknown;
  resetSaveStatus(): void;
  safeSet(key: string, value: string): boolean;
  registerReclaimer(reclaim: () => void): () => void;
  /** Replace the global localStorage for one scenario; returns the restore. */
  installStorage(storage: Storage): () => void;
  hold(project: string, maxMs: number | undefined): () => void;
  isHeld(project: string): boolean;
  subscribeRelease(listener: (project: string) => void): () => void;
  writeDraft(scope: DraftScopeLike, input: Record<string, unknown>): boolean;
  readDraft(scope: DraftScopeLike): DraftLike | null;
  corruptDraft(scope: DraftScopeLike): void;
  /** The hydrate decision; returns its kind ("remote", "draft" or "conflict"). */
  decideHydrate(
    draft: DraftLike | null,
    remoteRevision: number | null,
    remoteNodes: unknown[],
    remoteMetadata: Record<string, unknown> | null,
  ): Promise<string>;
  prune(now: number): void;
  draftMaxBytes: number;
  clearStorage(): void;
  advanceTimers(ms: number): void;
}

export type Op = { op: string } & Record<string, unknown>;

export interface ScenarioCase {
  id: string;
  behaviors: string[];
  kind: "session" | "decision" | "hold" | "draft" | "hydrate" | "status" | "quota";
  ops: Op[];
}

const flush = async (): Promise<void> => {
  for (let index = 0; index < 5; index += 1) await Promise.resolve();
};

async function runSession(impl: RecoveryImpl, ops: Op[]): Promise<unknown[]> {
  const pending: { version: number; resolve: (value: boolean) => void; reject: (error: unknown) => void }[] = [];
  const runVersions: number[] = [];
  const events: string[] = [];
  let sessions: SaveSessionLike[] = [];
  let generation = 0;
  const open = () => {
    generation += 1;
    const session = impl.createSession(`p:c${generation}`, generation, (version) => {
      runVersions.push(version);
      return new Promise<boolean>((resolve, reject) => pending.push({ version, resolve, reject }));
    });
    sessions.push(session);
    return session;
  };
  open();
  const out: unknown[] = [];
  for (const op of ops) {
    const session = sessions[sessions.length - 1];
    let value: unknown = null;
    if (op.op === "request") {
      const tag = String(op.tag);
      void session.requestSave().then((persisted) => events.push(`${tag}:${persisted}`));
    } else if (op.op === "resolve") {
      const next = pending.shift();
      if (next) {
        if (op.value === "throw") next.reject(new Error("boom"));
        else next.resolve(Boolean(op.value));
      }
    } else if (op.op === "dispose") {
      session.dispose();
    } else if (op.op === "switch") {
      session.dispose();
      open();
    } else if (op.op === "unsavedBeyond") {
      value = session.hasUnsavedContentBeyond(Number(op.version));
    }
    await flush();
    const current = sessions[sessions.length - 1];
    out.push({
      op: op.op,
      value,
      contentVersion: current.contentVersion(),
      savedVersion: current.savedVersion(),
      saving: current.isSaving(),
      disposed: sessions.map((item) => item.isDisposed()),
      pending: pending.map((item) => item.version),
      runVersions: [...runVersions],
      events: [...events],
    });
  }
  sessions = [];
  return out;
}

function runDecision(impl: RecoveryImpl, ops: Op[]): unknown[] {
  return ops.map((op) => {
    if (op.op === "decide") return impl.decideSaveAction(op.snapshot as Record<string, unknown>);
    if (op.op === "classify") return impl.classifySave((op.status as number | null) ?? null, op.detail as string | undefined);
    return impl.checkPayloadLimits(Number(op.nodes), Number(op.edges), (op.size as number | null) ?? null);
  });
}

function runStatus(impl: RecoveryImpl, ops: Op[]): unknown[] {
  impl.resetSaveStatus();
  return ops.map((op) => {
    if (op.op === "set") {
      impl.setSaveStatus(String(op.scope), String(op.status), op.error as string | undefined);
      return { op: op.op };
    }
    if (op.op === "advance") {
      impl.advanceTimers(Number(op.ms));
      return { op: op.op };
    }
    return { op: op.op, state: impl.deriveSaveStatus(String(op.scope)) };
  });
}

function runHold(impl: RecoveryImpl, ops: Op[]): unknown[] {
  const releases = new Map<string, () => void>();
  const events: string[] = [];
  const unsubscribe = impl.subscribeRelease((project) => events.push(project));
  const out = ops.map((op) => {
    if (op.op === "hold") releases.set(String(op.token), impl.hold(String(op.project), op.maxMs as number | undefined));
    else if (op.op === "release") releases.get(String(op.token))?.();
    else if (op.op === "advance") impl.advanceTimers(Number(op.ms));
    return { op: op.op, heldA: impl.isHeld("a"), heldB: impl.isHeld("b"), events: [...events] };
  });
  unsubscribe();
  for (const release of releases.values()) release();
  return out;
}

function draftInput(op: Op, maxBytes: number): Record<string, unknown> {
  const pad = (count: unknown) => "x".repeat(typeof count === "number" ? Math.round(count * maxBytes) : 0);
  return {
    baseRevision: op.baseRevision ?? 1,
    nodes: Array.from({ length: Number(op.nodes ?? 1) }, (_, index) => ({
      id: `n${index}`,
      type: "note",
      position: { x: 0, y: 0 },
      data: { label: index === 0 ? pad(op.contentFraction) : "" },
    })),
    edges: [],
    viewport: null,
    metadata: (op.metadata as Record<string, unknown> | undefined) ?? null,
    history:
      op.historyFraction === undefined
        ? null
        : { past: [{ nodes: [{ id: "h", type: "note", position: { x: 0, y: 0 }, data: { label: pad(op.historyFraction) } }], edges: [] }], future: [] },
    mutation: { userEditsSinceHydrate: 1, lastMutationSource: "user_edit", pendingClearIntent: false },
    updatedAt: op.updatedAt ?? 10,
  };
}

function summarizeDraft(draft: DraftLike | null): unknown {
  if (!draft) return null;
  return {
    baseRevision: draft.baseRevision,
    nodes: draft.nodes.length,
    history: draft.history === null ? null : "kept",
    mutation: draft.mutation,
    updatedAt: draft.updatedAt,
  };
}

function runDraft(impl: RecoveryImpl, ops: Op[]): unknown[] {
  impl.clearStorage();
  return ops.map((op) => {
    const scope = { user: String(op.user ?? "u"), project: String(op.project ?? "p"), canvas: String(op.canvas ?? "c") };
    if (op.op === "write") return { op: op.op, stored: impl.writeDraft(scope, draftInput(op, impl.draftMaxBytes)) };
    if (op.op === "read") return { op: op.op, draft: summarizeDraft(impl.readDraft(scope)) };
    if (op.op === "corrupt") {
      impl.corruptDraft(scope);
      return { op: op.op };
    }
    impl.prune(Number(op.now));
    return { op: op.op };
  });
}

function noteNodes(labels: unknown): unknown[] {
  return (labels as string[]).map((label, index) => ({
    id: `n${index}`,
    type: "note",
    position: { x: 0, y: 0 },
    data: { label },
  }));
}

/** Each op stores a draft (or none), then asks the hydrate decision against the given server content. */
async function runHydrate(impl: RecoveryImpl, ops: Op[]): Promise<unknown[]> {
  const out: unknown[] = [];
  for (const op of ops) {
    impl.clearStorage();
    const scope = { user: "u", project: "p", canvas: "c" };
    if (op.draft !== null) {
      const draft = op.draft as Record<string, unknown>;
      impl.writeDraft(scope, {
        ...draftInput({ op: "write" }, impl.draftMaxBytes),
        baseRevision: draft.baseRevision ?? null,
        nodes: noteNodes(draft.labels),
        metadata: (draft.metadata as Record<string, unknown> | undefined) ?? null,
      });
    }
    const stored = impl.readDraft(scope);
    out.push(
      await impl.decideHydrate(
        stored,
        (op.remoteRevision as number | null) ?? null,
        noteNodes(op.remoteLabels),
        (op.remoteMetadata as Record<string, unknown> | undefined) ?? null,
      ),
    );
  }
  return out;
}

/** A Storage with a byte budget that throws a QuotaExceededError when a write would exceed it. */
function budgetStorage(budget: number, errorName: string): Storage {
  const data = new Map<string, string>();
  const used = () => [...data].reduce((total, [key, value]) => total + key.length + value.length, 0);
  return {
    get length() {
      return data.size;
    },
    key: (index: number) => [...data.keys()][index] ?? null,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      const previous = data.get(key);
      const next = used() - (previous === undefined ? 0 : key.length + previous.length) + key.length + value.length;
      if (next > budget) throw new DOMException("quota", errorName);
      data.set(key, value);
    },
    removeItem: (key: string) => {
      data.delete(key);
    },
    clear: () => data.clear(),
  };
}

function runQuota(impl: RecoveryImpl, ops: Op[]): unknown[] {
  const storage = budgetStorage(Number(ops[0]?.budget ?? 100), String(ops[0]?.errorName ?? "QuotaExceededError"));
  const restore = impl.installStorage(storage);
  const unregister: (() => void)[] = [];
  try {
    return ops.map((op) => {
      if (op.op === "reclaimer") {
        const prefix = String(op.prefix);
        unregister.push(
          impl.registerReclaimer(() => {
            for (const key of [...Array(storage.length).keys()].map((index) => storage.key(index))) {
              if (key?.startsWith(prefix)) storage.removeItem(key);
            }
          }),
        );
      } else if (op.op === "seed") {
        storage.setItem(String(op.key), "x".repeat(Number(op.size)));
      } else if (op.op === "set") {
        return { op: op.op, stored: impl.safeSet(String(op.key), "v".repeat(Number(op.size))), keys: storage.length };
      }
      return { op: op.op, keys: storage.length };
    });
  } finally {
    for (const release of unregister) release();
    restore();
  }
}

export async function runScenario(impl: RecoveryImpl, fixture: ScenarioCase): Promise<unknown[]> {
  if (fixture.kind === "quota") return runQuota(impl, fixture.ops);
  if (fixture.kind === "hydrate") return runHydrate(impl, fixture.ops);
  if (fixture.kind === "status") return runStatus(impl, fixture.ops);
  if (fixture.kind === "session") return runSession(impl, fixture.ops);
  if (fixture.kind === "decision") return runDecision(impl, fixture.ops);
  if (fixture.kind === "hold") return runHold(impl, fixture.ops);
  return runDraft(impl, fixture.ops);
}
