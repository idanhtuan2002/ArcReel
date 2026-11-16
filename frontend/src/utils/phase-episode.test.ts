import { describe, expect, it } from "vitest";
import { phaseEpisode } from "./phase-episode";

describe("phaseEpisode", () => {
  it("names the first unfinished episode once one is finished, and done when all are", () => {
    expect(phaseEpisode({ total: 10, scripted: 1, in_production: 0, completed: 1 })).toBe(2);
    expect(phaseEpisode({ total: 10, scripted: 3, in_production: 1, completed: 0 })).toBeNull();
    expect(phaseEpisode({ total: 7, scripted: 7, in_production: 0, completed: 7 })).toBe("done");
    expect(phaseEpisode({ total: 0, scripted: 0, in_production: 0, completed: 0 })).toBeNull();
    expect(phaseEpisode(undefined)).toBeNull();
  });
});
