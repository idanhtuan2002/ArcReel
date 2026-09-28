import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { ProjectAdmissionToggle } from "./ProjectAdmissionToggle";
import { useAppStore } from "@/stores/app-store";

describe("ProjectAdmissionToggle", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.restoreAllMocks();
  });

  it("shows the project's pause state and toggles it", async () => {
    vi.spyOn(API, "getAdmission").mockResolvedValue({ paused: ["demo"], max_running_per_project: 0 });
    const setSpy = vi.spyOn(API, "setProjectPaused").mockResolvedValue({ project: "demo", paused: false });

    render(<ProjectAdmissionToggle projectName="demo" />);
    const box = screen.getByLabelText("暂停本项目");
    await waitFor(() => expect(box).toBeChecked());

    fireEvent.click(box);

    await waitFor(() => expect(setSpy).toHaveBeenCalledWith("demo", false));
    await waitFor(() => expect(box).not.toBeChecked());
  });

  it("reports a failed update", async () => {
    vi.spyOn(API, "getAdmission").mockResolvedValue({ paused: [], max_running_per_project: 0 });
    vi.spyOn(API, "setProjectPaused").mockRejectedValue(new Error("boom"));

    render(<ProjectAdmissionToggle projectName="demo" />);
    const box = screen.getByLabelText("暂停本项目");
    await waitFor(() => expect(box).toBeEnabled());
    fireEvent.click(box);

    await waitFor(() => expect(useAppStore.getState().toast?.text).toContain("更新失败"));
  });
});
