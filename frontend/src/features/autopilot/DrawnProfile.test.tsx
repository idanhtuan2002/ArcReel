import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";

import i18n from "@/i18n";

import { storyAutopilot } from "./AutopilotPanel";
import { DrawnProfile } from "./DrawnProfile";

beforeAll(async () => {
  await i18n.changeLanguage("en");
});

describe("story autopilot without an idea", () => {
  it("leaves an empty idea and length out and refuses an invalid length", () => {
    expect(storyAutopilot("  ", null, "")).toEqual({});
    expect(storyAutopilot("Chuyến đò cuối.", 12, "")).toEqual({ idea: "Chuyến đò cuối.", book_chapters: 12 });
    expect(storyAutopilot("", 3, "")).toBeNull();
  });

  it("shows what the system chose and marks a defaulted value", () => {
    render(
      <DrawnProfile
        profile={{
          title: "Chuyến đò cuối",
          idea: "Một lái đò già chở người khách cuối cùng.",
          genre_pack: "mystery",
          tone: "hồi hộp",
          audience: "phổ thông",
          book_chapters: 18,
          defaulted: ["tone"],
        }}
      />,
    );
    expect(screen.getByText("Chuyến đò cuối")).toBeInTheDocument();
    const chips = screen.getAllByRole("listitem").map((chip) => chip.textContent);
    expect(chips).toEqual(["Genre: Mystery", "Tone: hồi hộp *", "Readers: phổ thông", "Length: 18 chapters"]);
    expect(screen.getByTitle("Default value: the model's choice was outside the allowed list")).toHaveTextContent(
      "hồi hộp",
    );
  });
});
