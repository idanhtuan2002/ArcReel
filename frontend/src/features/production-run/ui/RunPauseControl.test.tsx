import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "../api/productionRunClient";
import type { RunSnapshot } from "../api/types";
import { RunPauseControl } from "./RunPauseControl";

const RUN = { run_id: "r1", status: "WAITING_TASK", version: 3, input_digest: "sha256:i", policy_digest: "sha256:p" };

describe("RunPauseControl", () => {
  afterEach(() => vi.restoreAllMocks());

  it("pauses only after asking, and never toggles the details it sits in", async () => {
    const paused = { ...RUN, status: "PAUSED" } as unknown as RunSnapshot;
    const control = vi.spyOn(client, "controlProductionRun").mockResolvedValue(paused);
    const onPaused = vi.fn();
    const { container } = render(
      <details open>
        <summary>
          <RunPauseControl projectName="demo" run={RUN as unknown as RunSnapshot} onPaused={onPaused} />
        </summary>
      </details>,
    );
    const details = container.querySelector("details");

    await userEvent.click(screen.getByRole("button", { name: "暂停运行" }));
    expect(control).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "不暂停" }));
    await userEvent.click(screen.getByRole("button", { name: "暂停运行" }));
    await userEvent.click(screen.getByRole("button", { name: "暂停" }));

    expect(control).toHaveBeenCalledWith("demo", "r1", "pause", expect.objectContaining({ expected_version: 3 }));
    expect(onPaused).toHaveBeenCalledWith(paused);
    expect(details).toHaveAttribute("open");
  });
});
