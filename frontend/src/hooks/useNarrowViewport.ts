import { useSyncExternalStore } from "react";

/** 窄屏（手机竖屏）断点：与 Tailwind `md` 断点对齐，低于它时工作区改用单栏布局。 */
export const NARROW_VIEWPORT_QUERY = "(max-width: 767px)";

function media(): MediaQueryList | null {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(NARROW_VIEWPORT_QUERY)
    : null;
}

function subscribe(onChange: () => void): () => void {
  const list = media();
  if (!list) return () => undefined;
  list.addEventListener("change", onChange);
  return () => list.removeEventListener("change", onChange);
}

/** 视口是否处于窄屏断点；不支持 matchMedia 的环境按宽屏处理。 */
export function useNarrowViewport(): boolean {
  return useSyncExternalStore(subscribe, () => media()?.matches ?? false, () => false);
}
