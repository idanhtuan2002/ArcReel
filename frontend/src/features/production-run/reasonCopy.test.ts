import { describe, expect, it } from "vitest";
import i18n from "@/i18n";
import { describeReason } from "./reasonCopy";

describe("describeReason", () => {
  const t = i18n.t.bind(i18n);

  it("reads a known code in words with its next step", () => {
    const copy = describeReason(t, "ADAPTATION_FAILED");
    expect(copy.text).toBe("写作模型多次尝试后仍未能把本集改编成剧本");
    expect(copy.hint).toContain("重置分集规划");
    expect(copy.code).toBe("ADAPTATION_FAILED");
  });

  it("falls back to the family sentence, then to a generic one, always naming the code", () => {
    expect(describeReason(t, "MEDIA_VIDEO_SHORTER_THAN_TTS").text).toBe(
      "媒体工具拒绝了请求（MEDIA_VIDEO_SHORTER_THAN_TTS）",
    );
    const generic = describeReason(t, "SOMETHING_NEW");
    expect(generic.text).toBe("运行在此步骤停止（SOMETHING_NEW）");
    expect(generic.hint).toBeNull();
  });
});
