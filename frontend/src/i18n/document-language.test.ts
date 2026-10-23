import { afterEach, describe, expect, it } from "vitest";

import i18n from "./index";

afterEach(async () => {
  await i18n.changeLanguage("zh");
});

describe("document language", () => {
  it("follows the interface language so styles and fonts can switch per script", async () => {
    await i18n.changeLanguage("vi");
    expect(document.documentElement.lang).toBe("vi");
    await i18n.changeLanguage("en");
    expect(document.documentElement.lang).toBe("en");
  });
});
