import { useState } from "react";
import { useTranslation } from "react-i18next";

interface ConflictBannerProps {
  /** "kept": the version is stored on this device. "unkept": it is held in memory until the tab closes. */
  mode: "kept" | "unkept";
  onUseMine: () => void;
  onDiscardMine: () => void;
}

/** Shown while local work is kept aside after another tab or device saved the Canvas. */
export function ConflictBanner({ mode, onUseMine, onDiscardMine }: ConflictBannerProps) {
  const { t } = useTranslation("dashboard");
  // Discarding deletes the kept-aside work for good, so it takes a second, confirming click.
  const [confirming, setConfirming] = useState(false);
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 cc-conflict border-b border-warm-ring px-4 py-2 text-sm">
      <span className="font-mono text-[10px] tracking-[0.18em] text-warm">CONFLICT</span>
      <p className="min-w-0 flex-1 text-text-2">
        <span className="font-medium text-text">{t("creative_canvas_conflict_title")}</span>{" "}
        {mode === "kept" ? t("creative_canvas_conflict_body") : t("creative_canvas_conflict_unkept_body")}
      </p>
      <button
        type="button"
        onClick={onUseMine}
        className="cc-btn-warm rounded-md px-3 py-1 text-xs font-medium"
      >
        {t("creative_canvas_conflict_use_mine")}
      </button>
      <button
        type="button"
        onClick={() => (confirming ? onDiscardMine() : setConfirming(true))}
        className="rounded-md border border-hairline-strong px-3 py-1 text-xs text-text-2 hover:text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        {confirming ? t("creative_canvas_conflict_confirm_discard") : t("creative_canvas_conflict_discard_mine")}
      </button>
    </div>
  );
}
