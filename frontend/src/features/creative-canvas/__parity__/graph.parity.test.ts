import { describe, expect, it } from "vitest";

import fixtures from "../__fixtures__/parity/graph.json";
import {
  type FixtureCase,
  type GraphObservation,
  runGraphCase,
} from "./graphAdapter";

const cases = fixtures.cases as unknown as FixtureCase[];

describe("graph parity fixtures on the port", () => {
  it.each(cases.map((fixture) => [fixture.id, fixture] as const))(
    "%s replays",
    (_id, fixture) => {
      const observations = runGraphCase(fixture);

      expect(observations).toHaveLength(fixture.ops.length);
    },
  );

  it("matches the recorded port observations (the parity harness input)", async () => {
    const results: Record<string, GraphObservation[]> = {};
    for (const fixture of cases) results[fixture.id] = runGraphCase(fixture);

    await expect(
      `${JSON.stringify({ fixture_set: fixtures.fixture_set, results }, null, 2)}\n`,
    ).toMatchFileSnapshot("../__fixtures__/parity/graph.port.json");
  });
});
