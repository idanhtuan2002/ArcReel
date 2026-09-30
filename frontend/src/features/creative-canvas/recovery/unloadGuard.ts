/**
 * Work that exists only in memory is lost when the browser tab closes. While any
 * such work is registered, the page asks the browser to confirm unloading. The
 * guard is app-wide: it outlives leaving the Canvas page, since in-memory
 * kept-aside versions do too.
 */

const unstored = new Set<string>();
let installed = false;

function onBeforeUnload(event: BeforeUnloadEvent): void {
  if (unstored.size > 0) event.preventDefault();
}

/** Mark or clear one piece of work that has no durable copy. */
export function setUnstoredWork(key: string, unstoredNow: boolean): void {
  if (unstoredNow) {
    unstored.add(key);
    if (!installed && typeof window !== "undefined") {
      window.addEventListener("beforeunload", onBeforeUnload);
      installed = true;
    }
  } else {
    unstored.delete(key);
  }
}

/** Whether any work would be lost if the tab closed now. */
export function hasUnstoredWork(): boolean {
  return unstored.size > 0;
}

/** Test helper. */
export function resetUnstoredWork(): void {
  unstored.clear();
}
