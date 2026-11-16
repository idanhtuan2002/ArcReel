import type { TFunction } from "i18next";

/** Reason codes whose family prefix has its own sentence (``MEDIA_<CODE>`` from a media tool refusal and so on). */
const FAMILIES = ["MEDIA", "WORKFLOW", "RENDER", "MASTER", "PROJECT"] as const;

export interface ReasonCopy {
  /** What happened, in plain words. */
  text: string;
  /** What to do next, when there is advice for this code. */
  hint: string | null;
  /** The code itself, for the technical details and support. */
  code: string;
}

/**
 * The words for a run's stop or refusal reason: its own sentence, else its family's sentence, else a generic one that
 * names the code. A code is never the only thing a person reads.
 */
export function describeReason(t: TFunction, code: string): ReasonCopy {
  const own = t(`auto_reason_${code}`, { ns: "workflow", defaultValue: "" });
  let text = own;
  if (!text) {
    const family = FAMILIES.find((prefix) => code.startsWith(`${prefix}_`));
    text = family
      ? t(`auto_reason_family_${family}`, { ns: "workflow", code })
      : t("auto_reason_generic", { ns: "workflow", code });
  }
  const hint = t(`auto_reason_hint_${code}`, { ns: "workflow", defaultValue: "" });
  return { text, hint: hint || null, code };
}
