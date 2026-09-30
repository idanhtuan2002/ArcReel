/**
 * Shared measurement runner of the M8-B parity harnesses (performance and resource
 * dimensions). Imports nothing: the donor side and the port side pass their own
 * case runner and byte measure, so both measure the same fixture cases the same way.
 *
 * Each case is replayed WARMUP times, then REPS times. The result records:
 * - the median and p95 wall time;
 * - the resident bytes of one run (`resident_bytes`): the size of the structured-clone
 *   serialization (`node:v8` `serialize`, passed in as `residentBytes`) of what the run
 *   leaves resident: the final graph state for a graph harness, the results of pure
 *   functions, the final scenario state and localStorage entries for save and recovery.
 *   The serialization keeps shared references once, so it counts the data a run holds,
 *   not how often it is referenced. JS heap counters (`heapUsed` after gc) could not
 *   resolve these kilobyte-sized states reproducibly; heap at Canvas scale is measured by
 *   the browser benchmark;
 * - the localStorage bytes (keys and values) present after the case;
 * - the size of the case's observations, for reference.
 */

export interface CaseTiming {
  reps: number;
  median_ms: number;
  p95_ms: number;
  resident_bytes: number;
  storage_bytes: number;
  observation_bytes: number;
}

const WARMUP = 5;
const REPS = 25;

// Captured at import, before a harness installs fake timers.
const now = performance.now.bind(performance);

function rank(sorted: number[], percentile: number): number {
  return sorted[Math.max(0, Math.ceil((percentile / 100) * sorted.length) - 1)];
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

/** The localStorage entries, as resident state of a save and recovery scenario. */
export function storageEntries(): Record<string, string> {
  const storage = (globalThis as { localStorage?: Storage }).localStorage;
  const out: Record<string, string> = {};
  if (!storage) return out;
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index) ?? "";
    out[key] = storage.getItem(key) ?? "";
  }
  return out;
}

export async function timeCases<C extends { id: string }>(
  cases: readonly C[],
  run: (fixture: C) => unknown,
  residentBytes: (value: unknown) => number,
): Promise<Record<string, CaseTiming>> {
  const out: Record<string, CaseTiming> = {};
  for (const fixture of cases) {
    let last: unknown = null;
    for (let index = 0; index < WARMUP; index += 1) last = await run(fixture);
    const samples: number[] = [];
    for (let index = 0; index < REPS; index += 1) {
      const start = now();
      last = await run(fixture);
      samples.push(now() - start);
    }
    samples.sort((a, b) => a - b);
    out[fixture.id] = {
      reps: REPS,
      median_ms: Number(rank(samples, 50).toFixed(4)),
      p95_ms: Number(rank(samples, 95).toFixed(4)),
      resident_bytes: residentBytes(last),
      storage_bytes: storageBytes(),
      observation_bytes: JSON.stringify(last).length,
    };
  }
  return out;
}
