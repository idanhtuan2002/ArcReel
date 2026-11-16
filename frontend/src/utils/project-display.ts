// 项目显示名解析:trim 后非空用原值,否则塌成调用方传入的 i18n 兜底文案。
// 抽出 helper 是因为 fallback 模式在多处显示位置重复,且早期把内部 slug-style
// project_name 当显示名暴露给用户引发过报障(中文标题被 NFKD 后剩纯 hex)。
export function getProjectDisplayName(
  rawTitle: string | null | undefined,
  untitledLabel: string,
): string {
  // A title taken from a Markdown story keeps its heading marks ("# Title", "Title ### Subtitle"); they are not part
  // of the name: a leading run is dropped and an inner run separates the parts.
  const trimmed = rawTitle
    ?.trim()
    .replace(/^#{1,6}\s+/, "")
    .replace(/\s+#{1,6}\s+/g, " · ")
    .trim();
  return trimmed && trimmed.length > 0 && !/^#+$/.test(trimmed) ? trimmed : untitledLabel;
}
