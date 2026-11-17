import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "./api/productionRunClient";
import type { RunList } from "./api/types";
import { useProjectRuns, useRunsStore } from "./runsStore";

describe("useProjectRuns", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    useRunsStore.setState({ byProject: {} });
  });

  it("shares one reading of a project's runs between every component that shows them", async () => {
    const list = vi
      .spyOn(client, "listProductionRuns")
      .mockResolvedValue({ start: {}, runs: [{ run_id: "r1" }] } as unknown as RunList);

    const first = renderHook(() => useProjectRuns("demo"));
    const second = renderHook(() => useProjectRuns("demo"));

    await waitFor(() => expect(first.result.current?.[0]?.run_id).toBe("r1"));
    expect(second.result.current?.[0]?.run_id).toBe("r1");
    expect(list).toHaveBeenCalledTimes(1);
    first.unmount();
    second.unmount();
  });
});
