/**
 * Shared timing runner of the M8-B parity harnesses (performance and resource
 * dimensions). Imports nothing: the donor side and the port side pass their own
 * case runner, so both measure the same fixture cases the same way.
 *
 * Each case is replayed WARMUP times, then REPS times; the result records the
 * median and p95 wall time and the size of the case's observations in bytes.
 */

export interface CaseTiming {
  reps: number;
  median_ms: number;
  p95_ms: number;
  observation_bytes: number;
}

const WARMUP = 5;
// Captured at import, before a harness installs fake timers.
const now = performance.now.bind(performance);
const REPS = 25;

function rank(sorted: number[], percentile: number): number {
  return sorted[Math.max(0, Math.ceil((percentile / 100) * sorted.length) - 1)];
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
      observation_bytes: JSON.stringify(last).length,
    };
  }
  return out;
}
