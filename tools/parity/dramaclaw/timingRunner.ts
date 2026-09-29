/**
 * Shared measurement runner of the M8-B parity harnesses (performance and resource
 * dimensions). Imports nothing: the donor side and the port side pass their own
 * case runner, so both measure the same fixture cases the same way.
 *
 * Each case is replayed WARMUP times, then REPS times. The result records:
 * - the median and p95 wall time;
 * - the median JS heap the case retains, measured after garbage collection while
 *   its result is still referenced (null when the runtime exposes no `gc`: run with
 *   NODE_OPTIONS=--expose-gc);
 * - the localStorage bytes (keys and values) present after the case;
 * - the size of the case's observations, for reference.
 */

export interface CaseTiming {
  reps: number;
  median_ms: number;
  p95_ms: number;
  retained_heap_bytes: number | null;
  storage_bytes: number;
  observation_bytes: number;
}

const WARMUP = 5;
const REPS = 25;
// Captured at import, before a harness installs fake timers.
const now = performance.now.bind(performance);

type Runtime = { gc?: () => void; process?: { memoryUsage(): { heapUsed: number } } };
const runtime = globalThis as unknown as Runtime;

function rank(sorted: number[], percentile: number): number {
  return sorted[Math.max(0, Math.ceil((percentile / 100) * sorted.length) - 1)];
}

function settledHeap(): number | null {
  if (!runtime.gc || !runtime.process) return null;
  runtime.gc();
  runtime.gc();
  return runtime.process.memoryUsage().heapUsed;
}

function storageBytes(): number {
  const storage = (globalThis as { localStorage?: Storage }).localStorage;
  if (!storage) return 0;
  let total = 0;
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index) ?? "";
    total += key.length + (storage.getItem(key) ?? "").length;
  }
  return total;
}

export async function timeCases<C extends { id: string }>(
  cases: readonly C[],
  run: (fixture: C) => unknown,
): Promise<Record<string, CaseTiming>> {
  const out: Record<string, CaseTiming> = {};
  for (const fixture of cases) {
    let last: unknown = null;
    for (let index = 0; index < WARMUP; index += 1) last = await run(fixture);
    const samples: number[] = [];
    const retained: number[] = [];
    for (let index = 0; index < REPS; index += 1) {
      last = null;
      const before = settledHeap();
      const start = now();
      last = await run(fixture);
      samples.push(now() - start);
      const after = settledHeap();
      if (before !== null && after !== null && last !== undefined) retained.push(Math.max(0, after - before));
    }
    samples.sort((a, b) => a - b);
    retained.sort((a, b) => a - b);
    out[fixture.id] = {
      reps: REPS,
      median_ms: Number(rank(samples, 50).toFixed(4)),
      p95_ms: Number(rank(samples, 95).toFixed(4)),
      retained_heap_bytes: retained.length === REPS ? rank(retained, 50) : null,
      storage_bytes: storageBytes(),
      observation_bytes: JSON.stringify(last).length,
    };
  }
  return out;
}
