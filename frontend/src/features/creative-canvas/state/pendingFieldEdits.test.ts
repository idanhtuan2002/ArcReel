import { describe, expect, it, vi } from "vitest";

import { flushPendingFieldEdits, registerPendingFieldEdit } from "./pendingFieldEdits";

describe("pending field edits", () => {
  it("flushes every registered field until it unregisters", () => {
    const first = vi.fn();
    const second = vi.fn();
    const unregister = registerPendingFieldEdit(first);
    registerPendingFieldEdit(second);

    flushPendingFieldEdits();
    unregister();
    flushPendingFieldEdits();

    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(2);
  });
});
