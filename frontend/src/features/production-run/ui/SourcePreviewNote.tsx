import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";

export interface SourcePreview {
  rel_path: string;
  chars: number;
  chapters: number;
  headings: string[];
  warnings: string[];
}

/** What a run would read from the project's sources: chapters found, size and warnings (ADR-0118). */
export function SourcePreviewNote({ projectName }: { projectName: string }) {
  const { t } = useTranslation("workflow");
  const [sources, setSources] = useState<SourcePreview[] | null>(null);
  useEffect(() => {
    let live = true;
    void API.request<{ sources: SourcePreview[] }>(
      `/projects/${encodeURIComponent(projectName)}/story-sources/preview`,
    )
      .then((result) => {
        if (live) setSources(Array.isArray(result?.sources) ? result.sources : []);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [projectName]);
  if (sources === null) return null;
  if (sources.length === 0) {
    return (
      <p className="text-[12px]" style={{ color: "var(--color-text-3)" }}>
        {t("source_preview_empty")}
      </p>
    );
  }
  const chapters = sources.reduce((sum, item) => sum + item.chapters, 0);
  const chars = sources.reduce((sum, item) => sum + item.chars, 0);
  return (
    <div className="space-y-0.5 text-[12px]" style={{ color: "var(--color-text-3)" }}>
      <p>{t("source_preview_summary", { files: sources.length, chapters, chars: chars.toLocaleString() })}</p>
      {sources.flatMap((item) =>
        item.warnings.map((warning) => (
          <p key={`${item.rel_path}-${warning}`} style={{ color: "var(--color-warning, var(--color-text-2))" }}>
            {item.rel_path}: {t(`source_preview_${warning}`)}
          </p>
        )),
      )}
    </div>
  );
}
