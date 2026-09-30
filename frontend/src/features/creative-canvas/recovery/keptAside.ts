/**
 * Local versions of a Canvas kept aside for the user to settle, oldest first.
 *
 * A version is kept aside when it conflicts with the server: a draft edited
 * from an older revision, or local work a save could not append because the
 * head moved. Each version is stored under its own localStorage key (the draft
 * TTL pruning covers these keys). When storage cannot take it, the version is
 * held in memory instead: that copy outlives closing and reopening the Canvas,
 * but not the browser tab, so the page warns before unloading while any exists.
 */

import {
  conflictScopeKey,
  readConflictSnapshot,
  type ConflictSnapshot,
  type DraftScope,
} from "./draftRecovery";
import { safeLocalStorageSet } from "./storageQuota";

export interface KeptAsideVersion {
  /** Its localStorage key, or null when it is held in memory only. */
  key: string | null;
  snapshot: ConflictSnapshot;
}

const inMemory = new Map<string, KeptAsideVersion[]>();
let sequence = 0;

function signature(snapshot: ConflictSnapshot): string {
  return JSON.stringify([snapshot.nodes, snapshot.edges, snapshot.metadata]);
}

function parse(raw: string | null): ConflictSnapshot | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<ConflictSnapshot>;
    if (!Array.isArray(parsed.nodes) || !Array.isArray(parsed.edges) || typeof parsed.timestamp !== "string") {
      return null;
    }
    return {
      nodes: parsed.nodes,
      edges: parsed.edges,
      viewport: parsed.viewport ?? null,
      metadata: parsed.metadata ?? null,
      timestamp: parsed.timestamp,
    };
  } catch {
    return null;
  }
}

function storedVersions(scope: DraftScope): KeptAsideVersion[] {
  const base = conflictScopeKey(scope);
  const out: KeptAsideVersion[] = [];
  try {
    // The single slot of earlier builds is read as the oldest version.
    const legacy = readConflictSnapshot(scope);
    if (legacy) out.push({ key: base, snapshot: legacy });
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (!key?.startsWith(`${base}#`)) continue;
      const snapshot = parse(localStorage.getItem(key));
      if (snapshot) out.push({ key, snapshot });
    }
  } catch {
    // Unavailable storage holds nothing.
  }
  return out;
}

function order(versions: KeptAsideVersion[]): KeptAsideVersion[] {
  return versions.sort((a, b) =>
    a.snapshot.timestamp === b.snapshot.timestamp
      ? (a.key ?? "~").localeCompare(b.key ?? "~")
      : a.snapshot.timestamp.localeCompare(b.snapshot.timestamp),
  );
}

/** Every version kept aside for this Canvas, oldest first, stored or in memory. */
export function readKeptAside(scope: DraftScope): KeptAsideVersion[] {
  return order([...storedVersions(scope), ...(inMemory.get(conflictScopeKey(scope)) ?? [])]);
}

/**
 * Keep a version aside, in storage when possible and in memory otherwise.
 * A version identical to one already kept is not added twice.
 */
export function keepAside(scope: DraftScope, snapshot: ConflictSnapshot): KeptAsideVersion {
  const existing = readKeptAside(scope).find((item) => signature(item.snapshot) === signature(snapshot));
  if (existing) return existing;
  const base = conflictScopeKey(scope);
  sequence += 1;
  const key = `${base}#${Date.parse(snapshot.timestamp) || 0}-${sequence}`;
  if (safeLocalStorageSet(key, JSON.stringify(snapshot))) return { key, snapshot };
  const version: KeptAsideVersion = { key: null, snapshot };
  inMemory.set(base, [...(inMemory.get(base) ?? []), version]);
  return version;
}

/** Remove a settled version from wherever it is kept. */
export function settleKeptAside(scope: DraftScope, version: KeptAsideVersion): void {
  if (version.key) {
    try {
      localStorage.removeItem(version.key);
    } catch {
      // Best-effort cleanup; a leftover copy is offered again, never lost.
    }
    return;
  }
  const base = conflictScopeKey(scope);
  const rest = (inMemory.get(base) ?? []).filter((item) => item !== version);
  if (rest.length > 0) inMemory.set(base, rest);
  else inMemory.delete(base);
}

/** Whether any version is held only in memory, which the browser tab closing would lose. */
export function hasUnstoredKeptAside(): boolean {
  return inMemory.size > 0;
}

/** Test helper: forget every in-memory version. */
export function resetKeptAsideMemory(): void {
  inMemory.clear();
}
