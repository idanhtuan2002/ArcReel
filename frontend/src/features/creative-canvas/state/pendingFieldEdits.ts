/**
 * Text fields hold typing locally and commit it on blur. Code that captures or
 * replaces the graph (keeping work aside, closing the Canvas) first flushes those
 * pending edits into the store, so no typed text is left behind.
 */
const flushers = new Set<() => void>();

export function registerPendingFieldEdit(flush: () => void): () => void {
  flushers.add(flush);
  return () => {
    flushers.delete(flush);
  };
}

export function flushPendingFieldEdits(): void {
  for (const flush of [...flushers]) flush();
}
