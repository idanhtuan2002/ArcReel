import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HelpHint } from "./HelpHint";

describe("HelpHint", () => {
  it("opens its explanation in place without triggering the surrounding control, and closes on Escape", () => {
    const onRowClick = vi.fn();
    render(
      <div onClick={onRowClick}>
        <HelpHint topic="Gates">Where a person approves.</HelpHint>
      </div>,
    );
    const button = screen.getByRole("button");
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(screen.getByRole("note")).toHaveTextContent("Where a person approves.");
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(onRowClick).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });

  it("closes when the person clicks elsewhere", () => {
    render(
      <>
        <HelpHint topic="Gates">Where a person approves.</HelpHint>
        <p>outside</p>
      </>,
    );
    fireEvent.click(screen.getByRole("button"));
    fireEvent.mouseDown(screen.getByText("outside"));
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});
