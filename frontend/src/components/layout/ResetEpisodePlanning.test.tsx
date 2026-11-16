import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { API } from "@/api";
import { useProjectsStore } from "@/stores/projects-store";
import { ResetEpisodePlanning } from "./ResetEpisodePlanning";

describe("ResetEpisodePlanning", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("names the consumed episodes, resets only after the second confirmation and refreshes the project", async () => {
    const request = vi
      .spyOn(API, "request")
      .mockResolvedValueOnce({
        confirmation_required: true,
        consumed_episodes: [2],
        removed_episodes: [],
        deleted_files: [],
        archived_files: [],
      })
      .mockResolvedValueOnce({
        confirmation_required: false,
        consumed_episodes: [],
        removed_episodes: [2, 3],
        deleted_files: [],
        archived_files: [],
      });
    const refreshProject = vi.fn().mockResolvedValue({ status: "ok" });
    useProjectsStore.setState({ refreshProject } as never);
    const user = userEvent.setup();

    render(<ResetEpisodePlanning projectName="demo" lastEpisode={10} />);
    await user.click(screen.getByRole("button", { name: "重置分集规划" }));
    const from = screen.getByRole("spinbutton");
    await user.clear(from);
    await user.type(from, "2");
    await user.click(screen.getByRole("button", { name: "重置" }));

    expect(await screen.findByText(/第 2 集已有剧本或媒体/)).toBeInTheDocument();
    expect(refreshProject).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "仍然重置" }));

    expect(await screen.findByText("已清除 2 集的规划；请重新分集。")).toBeInTheDocument();
    expect(request.mock.calls.map(([, init]) => JSON.parse(String(init?.body)))).toEqual([
      { from_episode: 2, confirm_consumed: false },
      { from_episode: 2, confirm_consumed: true },
    ]);
    expect(refreshProject).toHaveBeenCalledWith("demo");
  });
});
