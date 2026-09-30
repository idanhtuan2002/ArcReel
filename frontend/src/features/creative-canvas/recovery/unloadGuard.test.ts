import { beforeEach, describe, expect, it } from "vitest";

import { hasUnstoredWork, resetUnstoredWork, setUnstoredWork } from "./unloadGuard";

describe("unload guard", () => {
  beforeEach(() => {
    resetUnstoredWork();
  });

  it("asks the browser to confirm unloading while any work is unstored", () => {
    const unload = () => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };

    setUnstoredWork("a", true);
    setUnstoredWork("b", true);
    setUnstoredWork("a", false);
    expect(hasUnstoredWork()).toBe(true);
    expect(unload()).toBe(true);

    setUnstoredWork("b", false);
    expect(hasUnstoredWork()).toBe(false);
    expect(unload()).toBe(false);
  });
});
