/**
 * Shared measurement runner of the M8-B parity harnesses (performance and resource
 * dimensions). Imports nothing: the donor side and the port side pass their own
 * case runner, so both measure the same fixture cases the same way.
 *
 * Each case is replayed WARMUP times, then REPS times. The result records:
 * - the median and p95 wall time;
 * - the size of the state the case leaves resident (`footprint`): for a graph, its
 *   nodes, edges and every history snapshot's nodes and edges; null without a
 *   footprint function. JS heap counters cannot resolve states of a few kilobytes,
 *   so the footprint counts the retained entries instead; heap at Canvas scale is
 *   measured by the browser benchmark;
 * - the localStorage bytes (keys and values) present after the case;
 * - the size of the case's observations, for reference.
 */

export interface CaseTiming {
  reps: number;
  median_ms: number;
  p95_ms: number;
  state_entries: number | null;
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

interface GraphLike {
  nodes: readonly unknown[];
  edges: readonly unknown[];
  history?: { past: readonly GraphLike[]; future: readonly GraphLike[] };
}

/** Nodes, edges and every history snapshot's nodes and edges of a graph state. */
export function graphFootprint(state: GraphLike): number {
  const snapshots = [...(state.history?.past ?? []), ...(state.history?.future ?? [])];
  return state.nodes.length + state.edges.length + snapshots.reduce((sum, item) => sum + item.nodes.length + item.edges.length, 0);
}

export async function timeCases<C extends { id: string }>(
  cases: readonly C[],
  run: (fixture: C) => unknown,
  footprint?: (result: unknown) => number,
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
      state_entries: footprint ? footprint(last) : null,
      storage_bytes: storageBytes(),
      observation_bytes: JSON.stringify(last).length,
    };
  }
  return out;
}
