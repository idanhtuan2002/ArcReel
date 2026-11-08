import { describe, expect, it } from "vitest";

import { formatDuration, stageTimes, totalTime } from "./runTimeline";

const PROGRESS = {
  run_id: "run-1",
  stage: "STORY" as const,
  started_at: "2026-11-01T00:00:00Z",
  stages: [{ stage: "BRIEF" as const, finished_at: "2026-11-01T00:01:00Z" }],
  tasks: {},
};

describe("runTimeline", () => {
  it("times the current stage from the last pass while the run is active", () => {
    const now = Date.parse("2026-11-01T02:01:00Z");

    const times = stageTimes(PROGRESS, "STORY", true, now);

    expect(times.BRIEF).toEqual({ ms: 60_000, running: false });
    expect(times.STORY).toEqual({ ms: 2 * 3600_000, running: true });
    expect(totalTime(PROGRESS, true, now)).toBe(2 * 3600_000 + 60_000);
  });

  it("stops the clock at the last pass once the run has stopped", () => {
    const now = Date.parse("2026-11-02T00:00:00Z");

    expect(stageTimes(PROGRESS, "STORY", false, now).STORY).toBeUndefined();
    expect(totalTime(PROGRESS, false, now)).toBe(60_000);
  });

  it("has no times without a timeline", () => {
    expect(stageTimes(null, "STORY", true, 0)).toEqual({});
    expect(totalTime({ run_id: "r", stage: "BRIEF", tasks: {} }, true, 0)).toBeNull();
  });

  it("formats durations shortly", () => {
    expect(formatDuration(45_000)).toBe("45s");
    expect(formatDuration(22 * 60_000)).toBe("22m");
    expect(formatDuration((4 * 60 + 10) * 60_000)).toBe("4h 10m");
  });
});
