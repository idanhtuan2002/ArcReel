import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { ApiRequestError } from "@/api";

/** A refused autopilot change in words: its code and reasons, as the production run panel words them. */
export function useAutopilotErrorText() {
  const { t } = useTranslation("workflow");
  return useCallback(
    (cause: unknown): string => {
      if (cause instanceof ApiRequestError && cause.code) {
        const detail = cause.detail as { reasons?: unknown } | undefined;
        const reasons = Array.isArray(detail?.reasons)
          ? detail.reasons.map((reason) => t(`auto_reason_${String(reason)}`, { defaultValue: String(reason) }))
          : [];
        const head = t(`auto_error_${cause.code}`, {
          defaultValue: t(`dashboard:ap_error_${cause.code}`, { defaultValue: cause.code }),
        });
        return reasons.length ? `${head} (${reasons.join(", ")})` : head;
      }
      return cause instanceof Error ? cause.message : String(cause);
    },
    [t],
  );
}
