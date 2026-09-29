import { describe, expect, it } from "vitest";

import fixtures from "../__fixtures__/parity/groups.json";
import { type GroupCase, runGroupCase } from "./groupsAdapter";

const cases = fixtures.cases as unknown as GroupCase[];

describe("group parity fixtures on the port", () => {
  it.each(cases.map((fixture) => [fixture.id, fixture] as const))(
    "%s replays",
    (_id, fixture) => {
      expect(runGroupCase(fixture)).toHaveLength(fixture.ops.length);
    },
  );

  it("matches the recorded port observations (the parity harness input)", async () => {
    const results: Record<string, unknown[]> = {};
    for (const fixture of cases) results[fixture.id] = runGroupCase(fixture);

    await expect(
      `${JSON.stringify({ fixture_set: fixtures.fixture_set, results }, null, 2)}\n`,
    ).toMatchFileSnapshot("../__fixtures__/parity/groups.port.json");
  });
});
