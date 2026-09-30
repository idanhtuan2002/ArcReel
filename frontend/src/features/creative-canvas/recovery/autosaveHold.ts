/**
 * A hold on a project"s canvas autosave. Ported from DramaClaw b299bfd9
 * (`features/freezone/canvasAutosaveHold.ts`).
 *
 * While content is being rewritten in several steps (for example media
 * references being re-pointed), an autosave in the middle would persist a
 * half-rewritten state. The caller holds autosave first and releases it when
 * the rewrite ends, successfully or not; while held, only the local draft is
 * written, and a save runs on release. Every hold expires after a safety
 * maximum, so a lost release never blocks autosave for good.
 */

const DEFAULT_MAX_HOLD_MS = 90_000;

type ReleaseListener = (project: string) => void;

const holdsByProject = new Map<string, Set<symbol>>();
const listeners = new Set<ReleaseListener>();

function notifyRelease(project: string): void {
  for (const listener of [...listeners]) {
    try {
      listener(project);
    } catch (error) {
      console.warn("[canvas-autosave-hold] release listener failed", error);
    }
  }
}

/**
 * Hold `project`"s autosave and return its release. Holds stack: autosave
 * resumes when all are released. A hold older than `maxMs` releases itself.
 */
export function holdCanvasAutosave(
  project: string,
  options?: { maxMs?: number },
): () => void {
  const token = Symbol("canvas-autosave-hold");
  let holders = holdsByProject.get(project);
  if (!holders) {
    holders = new Set();
    holdsByProject.set(project, holders);
  }
  holders.add(token);

  let released = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const release = () => {
    if (released) {
      return;
    }
    released = true;
    if (timer != null) {
      clearTimeout(timer);
      timer = null;
    }
    const current = holdsByProject.get(project);
    if (!current) {
      return;
    }
    current.delete(token);
    if (current.size > 0) {
      return;
    }
    holdsByProject.delete(project);
    notifyRelease(project);
  };

  const maxMs = options?.maxMs ?? DEFAULT_MAX_HOLD_MS;
  if (Number.isFinite(maxMs) && maxMs > 0) {
    timer = setTimeout(() => {
      timer = null;
      console.warn("[canvas-autosave-hold] hold expired, resuming autosave", { project, maxMs });
      release();
    }, maxMs);
  }
  return release;
}

export function isCanvasAutosaveHeld(project: string): boolean {
  const holders = holdsByProject.get(project);
  return Boolean(holders && holders.size > 0);
}

/** Called once when every hold of a project is released. Returns the unsubscribe. */
export function subscribeCanvasAutosaveRelease(listener: ReleaseListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
