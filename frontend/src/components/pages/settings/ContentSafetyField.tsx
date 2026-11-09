import { useTranslation } from "react-i18next";

/** How strictly the project's stories are read for sensitive content (ADR-0121). */
export type ContentSafety = "strict" | "standard" | "mature" | "off";

export const CONTENT_SAFETY_LEVELS: ContentSafety[] = ["strict", "standard", "mature", "off"];

/** Sexual content involving minors is blocked at every level; the hint says so. */
export function ContentSafetyField({
  value,
  onChange,
}: {
  value: ContentSafety;
  onChange: (value: ContentSafety) => void;
}) {
  const { t } = useTranslation("dashboard");
  return (
    <div className="mt-4 text-[13px]">
      <label htmlFor="content-safety" style={{ color: "var(--color-text-1)" }}>
        {t("content_safety_label")}
      </label>
      <select
        id="content-safety"
        className="focus-ring mt-1 block rounded-md px-2 py-1"
        style={{ border: "1px solid var(--color-hairline-strong)", background: "transparent" }}
        value={value}
        aria-describedby="content-safety-hint"
        onChange={(event) => onChange(event.target.value as ContentSafety)}
      >
        {CONTENT_SAFETY_LEVELS.map((level) => (
          <option key={level} value={level}>
            {t(`content_safety_${level}`)}
          </option>
        ))}
      </select>
      <p id="content-safety-hint" className="mt-1 text-[12px]" style={{ color: "var(--color-text-3)" }}>
        {t(`content_safety_${value}_hint`)} {t("content_safety_always")}
      </p>
    </div>
  );
}
