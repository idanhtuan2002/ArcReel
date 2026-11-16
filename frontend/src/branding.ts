// Brand configuration — single source of truth for product naming.
// Override at build time via Vite env vars
// (VITE_BRAND_NAME / VITE_BRAND_TAGLINE / VITE_BRAND_DESCRIPTION).
//
// Source code references BRAND.name (or the [[brand]] placeholder in i18n
// resources) so the displayed product name is not hardcoded across files.
// Defaults preserve the upstream brand; downstream distributions can override
// via frontend/.env without code changes.

const env = import.meta.env as Record<string, string | undefined>;

function fallback(value: string | undefined, defaultValue: string): string {
  // Trim + empty check so VITE_BRAND_NAME="" (or whitespace) falls back to the
  // default, matching the documented "Empty = upstream defaults" contract.
  if (typeof value !== "string") return defaultValue;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : defaultValue;
}

export const BRAND = {
  name: fallback(env.VITE_BRAND_NAME, "ArcReel"),
  tagline: fallback(env.VITE_BRAND_TAGLINE, "Agent 驱动的 AI 视频创作工作台"),
  description: fallback(
    env.VITE_BRAND_DESCRIPTION,
    "AI 视频创作工作台，统一管理项目、脚本、分镜、视频生成与 Agent 对话。",
  ),
} as const;

export const BRAND_DOCUMENT_TITLE = `${BRAND.name} · ${BRAND.tagline}`;

const TAGLINE_OVERRIDE = fallback(env.VITE_BRAND_TAGLINE, "");

/** The browser tab title in the interface language; a distribution's own tagline (VITE_BRAND_TAGLINE) wins. */
export function brandDocumentTitle(translatedTagline: string | null): string {
  return `${BRAND.name} · ${TAGLINE_OVERRIDE || translatedTagline || BRAND.tagline}`;
}

