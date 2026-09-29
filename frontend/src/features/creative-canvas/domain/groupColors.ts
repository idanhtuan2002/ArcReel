/**
 * Group background colour presets. Ported from DramaClaw b299bfd9
 * (`features/canvas/domain/groupColors.ts`). `labelKey` is an i18n key; the
 * colour names follow the interface language.
 */

export interface GroupColorPreset {
  key: string;
  labelKey: string;
  /** Base colour hex. */
  value: string;
}

export const GROUP_COLOR_PRESETS: readonly GroupColorPreset[] = [
  { key: "red", labelKey: "creativeCanvas.groupColor.red", value: "#ef4444" },
  {
    key: "orange",
    labelKey: "creativeCanvas.groupColor.orange",
    value: "#f97316",
  },
  {
    key: "yellow",
    labelKey: "creativeCanvas.groupColor.yellow",
    value: "#eab308",
  },
  {
    key: "green",
    labelKey: "creativeCanvas.groupColor.green",
    value: "#22c55e",
  },
  { key: "cyan", labelKey: "creativeCanvas.groupColor.cyan", value: "#06b6d4" },
  { key: "blue", labelKey: "creativeCanvas.groupColor.blue", value: "#3b82f6" },
  {
    key: "purple",
    labelKey: "creativeCanvas.groupColor.purple",
    value: "#8b5cf6",
  },
  { key: "pink", labelKey: "creativeCanvas.groupColor.pink", value: "#ec4899" },
  { key: "gray", labelKey: "creativeCanvas.groupColor.gray", value: "#6b7280" },
];

/** The group card background: the base colour at about 12% opacity (8-digit hex). */
export function groupColorBackground(
  color: string | null | undefined,
): string | undefined {
  if (!color) return undefined;
  return `${color}1f`;
}

/** The group card border: the base colour at about 40% opacity (8-digit hex). */
export function groupColorBorder(
  color: string | null | undefined,
): string | undefined {
  if (!color) return undefined;
  return `${color}66`;
}
