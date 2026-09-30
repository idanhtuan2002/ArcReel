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
  // node:fs and node:v8 through runtime specifiers: the frontend TypeScript project carries no Node types.
  const [fsSpecifier, v8Specifier] = ["node:fs", "node:v8"];
  const fs = (await import(/* @vite-ignore */ fsSpecifier)) as { writeFileSync(path: string, data: string): void };
  const v8 = (await import(/* @vite-ignore */ v8Specifier)) as { serialize(value: unknown): { length: number } };
  const timing = await timeCases(cases, run, (value) => v8.serialize(value).length);
  fs.writeFileSync(timingOut, `${JSON.stringify(timing, null, 2)}\n`);
}
