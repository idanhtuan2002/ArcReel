// Test-only module-resolution hook for the Huohuo continuity-patch parity runner.
// It resolves exactly the specifiers listed in R2_STORY_DONOR_BASELINE.json (S07
// stubbed_imports) to modules whose exports throw when called, so the UNMODIFIED source
// can load without its model client and database. Never used by the ArcReel runtime.

const STUB_EXPORTS = {
  "../ai/ai.js": ["chatCompletionText"],
  "./novel-continuity-check.js": ["buildContinuityFixPlan", "formatContinuityFixInstructions", "formatRewriteAttemptHistory"],
  "./novel-continuity-deterministic-fix.js": ["applyDeterministicContinuityFixes"],
  "./novel-continuity.js": ["buildCanonLockPrefix", "resolveContinuityInjectBlock"],
};

export async function resolve(specifier, context, nextResolve) {
  if (Object.hasOwn(STUB_EXPORTS, specifier) && context.parentURL?.endsWith("novel-continuity-patch.ts")) {
    return { url: `stub:${specifier}`, shortCircuit: true };
  }
  return nextResolve(specifier, context);
}

export async function load(url, context, nextLoad) {
  if (url.startsWith("stub:")) {
    const names = STUB_EXPORTS[url.slice("stub:".length)];
    const source = names
      .map((name) => `export function ${name}() { throw new Error("stubbed donor import ${name} was called"); }`)
      .join("\n");
    return { format: "module", source, shortCircuit: true };
  }
  return nextLoad(url, context);
}
