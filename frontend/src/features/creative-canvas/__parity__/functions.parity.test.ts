import { describe, expect, it } from "vitest";

import fixtures from "../__fixtures__/parity/functions.json";
import { type FunctionCase, runFunctionCase } from "./functionsAdapter";

const cases = fixtures.cases as unknown as FunctionCase[];

describe("pure-function parity fixtures on the port", () => {
  it.each(cases.map((fixture) => [fixture.id, fixture] as const))(
    "%s calls only known functions",
    (_id, fixture) => {
      const results = runFunctionCase(fixture);

      expect(
        results.filter((result) =>
          JSON.stringify(result).includes("unknown function"),
        ),
      ).toEqual([]);
    },
  );

  it("matches the recorded port results (the parity harness input)", async () => {
    const results: Record<string, unknown[]> = {};
    for (const fixture of cases) results[fixture.id] = runFunctionCase(fixture);

    await expect(
      `${JSON.stringify({ fixture_set: fixtures.fixture_set, results }, null, 2)}\n`,
    ).toMatchFileSnapshot("../__fixtures__/parity/functions.port.json");
  });
});
