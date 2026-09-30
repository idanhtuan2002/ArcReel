import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mergeStoryboardGroup } from "../domain/groups";
import { commitEdit } from "../domain/graph";
import type { CanvasNode } from "../domain/types";
import { useCanvasStore } from "../state/canvasStore";
import { StoryboardFilmstrip } from "./StoryboardFilmstrip";

let ids = 0;
const deps = {
  newId: () => `g${(ids += 1)}`,
  naming: { group: () => "Group", storyboard: () => "Storyboard", copy: (name: string) => name, frame: () => "Frame" },
};

function frame(id: string, x: number): CanvasNode {
  return { id, type: "frame", position: { x, y: 0 }, data: { label: id, assetRef: `storyboards/${id}.png` } };
}

function seedStoryboard(): string {
  const store = useCanvasStore.getState();
  store.edit((graph) => commitEdit(graph, [frame("a", 0), frame("b", 400), frame("c", 800)], []));
  let groupId = "";
  store.edit((graph) => {
    const merged = mergeStoryboardGroup(graph, ["a", "b", "c"], deps);
    groupId = merged.groupId ?? "";
    return merged.state;
  });
  return groupId;
}

function names(): string[] {
  return within(screen.getByRole("listbox")).getAllByRole("option").map((option) => option.getAttribute("aria-label") ?? "");
}

describe("storyboard filmstrip", () => {
  beforeEach(() => {
    useCanvasStore.getState().reset();
  });

  it("explains how to make a storyboard when there is none", () => {
    render(<StoryboardFilmstrip onShowShot={vi.fn()} />);

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.getByText(/生成分镜板/)).toBeInTheDocument();
  });

  it("lists the shots in storyboard order as a labelled listbox with one tab stop", () => {
    seedStoryboard();
    render(<StoryboardFilmstrip onShowShot={vi.fn()} />);

    const options = within(screen.getByRole("listbox", { name: "分镜顺序" })).getAllByRole("option");
    expect(options).toHaveLength(3);
    expect(options.map((option) => option.tabIndex)).toEqual([0, -1, -1]);
    expect(options[0]).toHaveAttribute("aria-selected", "true");
  });

  it("moves focus with the arrow keys, Home and End", () => {
    seedStoryboard();
    render(<StoryboardFilmstrip onShowShot={vi.fn()} />);
    const list = screen.getByRole("listbox");
    const options = () => within(list).getAllByRole("option");

    fireEvent.keyDown(list, { key: "ArrowRight" });
    expect(options()[1]).toHaveFocus();
    fireEvent.keyDown(list, { key: "End" });
    expect(options()[2]).toHaveFocus();
    fireEvent.keyDown(list, { key: "ArrowRight" });
    expect(options()[2]).toHaveFocus();
    fireEvent.keyDown(list, { key: "Home" });
    expect(options()[0]).toHaveFocus();
  });

  it("reorders with Alt + arrow keys and announces the new position", () => {
    seedStoryboard();
    render(<StoryboardFilmstrip onShowShot={vi.fn()} />);
    expect(names()).toEqual(["镜头 1：a", "镜头 2：b", "镜头 3：c"]);

    fireEvent.keyDown(screen.getByRole("listbox"), { key: "ArrowRight", altKey: true });

    expect(names()).toEqual(["镜头 1：b", "镜头 2：a", "镜头 3：c"]);
    expect(screen.getByText("a 已移到第 2 位。")).toBeInTheDocument();
  });

  it("does not reorder past the ends of a storyboard", () => {
    seedStoryboard();
    render(<StoryboardFilmstrip onShowShot={vi.fn()} />);
    const seq = useCanvasStore.getState().editSeq;

    fireEvent.keyDown(screen.getByRole("listbox"), { key: "ArrowLeft", altKey: true });

    expect(useCanvasStore.getState().editSeq).toBe(seq);
  });

  it("shows the shot on the canvas with Enter or a click", () => {
    const groupId = seedStoryboard();
    const onShowShot = vi.fn();
    render(<StoryboardFilmstrip onShowShot={onShowShot} />);

    fireEvent.keyDown(screen.getByRole("listbox"), { key: "Enter" });
    fireEvent.click(within(screen.getByRole("listbox")).getAllByRole("option")[2]);

    expect(onShowShot.mock.calls).toEqual([
      [groupId, "a"],
      [groupId, "c"],
    ]);
  });
});
