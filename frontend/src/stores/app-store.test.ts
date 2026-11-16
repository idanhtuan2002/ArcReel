import { beforeEach, describe, expect, it } from "vitest";
import { useAppStore } from "./app-store";

const PANEL_OPEN_KEY = "arcreel_assistant_panel_open";

describe("assistant panel state", () => {
  beforeEach(() => {
    localStorage.clear();
    useAppStore.setState({
      assistantPanelOpen: false,
      assistantPanelInitialized: false,
    });
  });

  it.each([
    [false, true],
    [true, false],
  ])("keeps an explicit %s → %s choice across projects and page reloads", (initialOpen, expectedOpen) => {
    useAppStore.setState({ assistantPanelOpen: initialOpen });
    useAppStore.getState().toggleAssistantPanel();

    expect(localStorage.getItem(PANEL_OPEN_KEY)).toBe(String(expectedOpen));

    useAppStore.setState({
      assistantPanelOpen: !expectedOpen,
      assistantPanelInitialized: false,
    });
    useAppStore.getState().initializeAssistantPanel(!expectedOpen);

    expect(useAppStore.getState().assistantPanelOpen).toBe(expectedOpen);
  });

  it("defaults to the Agent credential availability when no choice is remembered", () => {
    useAppStore.getState().initializeAssistantPanel(false);
    expect(useAppStore.getState().assistantPanelOpen).toBe(false);

    useAppStore.setState({
      assistantPanelOpen: false,
      assistantPanelInitialized: false,
    });
    useAppStore.getState().initializeAssistantPanel(true);
    expect(useAppStore.getState().assistantPanelOpen).toBe(true);
  });

  it("does not remember a programmatic expansion", () => {
    useAppStore.getState().setAssistantPanelOpen(true);

    expect(useAppStore.getState().assistantPanelOpen).toBe(true);
    expect(localStorage.getItem(PANEL_OPEN_KEY)).toBeNull();

    useAppStore.setState({
      assistantPanelOpen: true,
      assistantPanelInitialized: false,
    });
    useAppStore.getState().initializeAssistantPanel(false);

    expect(useAppStore.getState().assistantPanelOpen).toBe(false);
  });
});

describe("project sidebar", () => {
  it("keeps a dragged width within bounds and remembers it, and toggles hidden", () => {
    useAppStore.getState().setSidebarWidth(999);
    expect(useAppStore.getState().sidebarWidth).toBe(420);
    useAppStore.getState().setSidebarWidth(10);
    expect(useAppStore.getState().sidebarWidth).toBe(200);
    useAppStore.getState().setSidebarWidth(300);
    useAppStore.getState().persistSidebarWidth();
    expect(window.localStorage.getItem("arcreel.sidebar.width")).toBe("300");

    const hidden = useAppStore.getState().sidebarHidden;
    useAppStore.getState().toggleSidebarHidden();
    expect(useAppStore.getState().sidebarHidden).toBe(!hidden);
    expect(window.localStorage.getItem("arcreel.sidebar.hidden")).toBe(hidden ? "0" : "1");
    useAppStore.getState().toggleSidebarHidden();
  });
});
