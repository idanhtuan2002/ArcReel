import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import { useAppStore } from "@/stores/app-store";
import type { RunSnapshot } from "./api/types";
import { useRunsStore } from "./runsStore";
import * as client from "./api/productionRunClient";
import { runNotification, useRunNotifications } from "./useRunNotifications";

function run(over: Partial<RunSnapshot>): RunSnapshot {
  return { run_id: "r1", status: "WAITING_TASK", stage: "MEDIA", targets: ["episode:2"], reason: null, ...over } as RunSnapshot;
}

const t = i18n.t.bind(i18n) as unknown as (key: string, options?: Record<string, unknown>) => string;

describe("run notifications", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    useRunsStore.setState({ byProject: {} });
    window.sessionStorage.clear();
  });

  it("say a stop with its reason, a finished film and a new stage, each leading to the run's controls", () => {
    const stopped = runNotification(run({ status: "BLOCKED_CONFIGURATION", reason: "ADAPTATION_FAILED" }), t);
    expect(stopped?.tone).toBe("warning");
    expect(stopped?.text).toContain("第 2 集");
    expect(stopped?.target).toEqual({ type: "run_controls", id: "r1", route: "/" });
    expect(runNotification(run({ status: "SUCCEEDED" }), t)?.tone).toBe("success");
    expect(runNotification(run({ status: "FAILED_QUALITY" }), t)?.tone).toBe("error");
    expect(runNotification(run({}), t)).toMatchObject({ tone: "info", read: true });
  });

  it("announce changes once, and on opening the page only a stop, not the stage a run is in", async () => {
    const push = vi.fn();
    useAppStore.setState({ pushWorkspaceNotification: push } as never);
    vi.spyOn(client, "listProductionRuns").mockResolvedValue({ start: {}, runs: [] } as never);
    useRunsStore.setState({ byProject: { demo: [run({})] } });

    const { rerender } = renderHook(() => useRunNotifications("demo"));
    expect(push).not.toHaveBeenCalled();

    useRunsStore.setState({ byProject: { demo: [run({ stage: "RENDER" })] } });
    rerender();
    expect(push).toHaveBeenCalledTimes(1);
    expect(push.mock.calls[0][0].tone).toBe("info");

    useRunsStore.setState({ byProject: { demo: [run({ stage: "RENDER", status: "BLOCKED_UNKNOWN" })] } });
    rerender();
    rerender();
    expect(push).toHaveBeenCalledTimes(2);
    expect(push.mock.calls[1][0].tone).toBe("warning");
  });
});
