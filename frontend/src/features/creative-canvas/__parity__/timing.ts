/**
 * Port side of the parity timing run: with PARITY_TIMING_OUT set, a parity test
 * times its fixture cases with the runner the donor side also uses and writes
 * the result there. Without it, the timing tests are skipped.
 */
import { timeCases } from "../../../../../tools/parity/dramaclaw/timingRunner";

const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {};

export const timingOut = env.PARITY_TIMING_OUT;

export async function writeTiming<C extends { id: string }>(
  cases: readonly C[],
  run: (fixture: C) => unknown,
): Promise<void> {
  if (!timingOut) return;
  // node:fs through a runtime specifier: the frontend TypeScript project carries no Node types.
  const specifier = "node:fs";
  const fs = (await import(/* @vite-ignore */ specifier)) as { writeFileSync(path: string, data: string): void };
  fs.writeFileSync(timingOut, `${JSON.stringify(await timeCases(cases, run), null, 2)}\n`);
}
