// The fixture is produced by r2/advanced_creative/digests.py and pinned on the Python side by
// tests/unit/r2/advanced_creative/test_m8b_canonical_digest_fixture.py; this file pins the port.
import { describe, expect, it } from "vitest";

import fixture from "../__fixtures__/canonical-digest.json";
import { CanonicalJsonError, canonicalJson, canonicalNumber, digestCanonical, digestPayload } from "./canonical";

describe("canonical JSON (differential against digests.py)", () => {
  it.each(fixture.values.map((item) => [item.name, item] as const))("encodes %s like the server", async (_name, item) => {
    const value: unknown = JSON.parse(item.input);

    expect(canonicalJson(value)).toBe(item.canonical);
    await expect(digestCanonical(value)).resolves.toBe(item.digest);
  });

  it.each(fixture.payloads.map((item) => [item.name, item] as const))(
    "digests the %s payload like the server",
    async (_name, item) => {
      const payload = JSON.parse(item.payload) as { kind: string };

      await expect(digestPayload(payload, JSON.parse(item.lineage))).resolves.toBe(item.digest);
    },
  );
});

describe("canonical JSON domain", () => {
  it("drops undefined object members as JSON.stringify does", () => {
    expect(canonicalJson({ a: 1, b: undefined })).toBe('{"a":1}');
  });

  it("writes negative zero as 0 and keeps fixed notation", () => {
    expect(canonicalNumber(-0)).toBe("0");
    expect(canonicalNumber(1.5e-8)).toBe("0.000000015");
    expect(canonicalNumber(-2e22)).toBe("-20000000000000000000000");
  });

  it.each([
    ["NaN", Number.NaN],
    ["Infinity", Number.POSITIVE_INFINITY],
    ["a lone surrogate", "\uD83C"],
    ["a key outside the BMP", { "🎬": 1 }],
    ["a Date", new Date(0)],
    ["a function", () => 1],
  ])("rejects %s", (_name, value) => {
    expect(() => canonicalJson(value)).toThrow(CanonicalJsonError);
  });
});
