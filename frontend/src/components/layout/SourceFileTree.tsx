import { useTranslation } from "react-i18next";
import { useLocation } from "wouter";
import { FileText, Plus } from "lucide-react";

/**
 * The project's source files as a branch of the workspace tree under "Source files", shaped like the story tree:
 * "Upload source files" on top (the upload page), then one row per file opening its reader.
 */
export function SourceFileTree({ files }: { files: readonly string[] | null }) {
  const { t } = useTranslation("dashboard");
  const [location, navigate] = useLocation();
  const onUpload = location === "/source";
  const current = location.startsWith("/source/") ? decodeURIComponent(location.slice("/source/".length)) : null;

  return (
    <ul className="mb-1 ml-[18px] space-y-px border-l border-hairline-soft pl-2" aria-label={t("source_tree_label")}>
      <li>
        <button
          type="button"
          onClick={() => navigate("/source")}
          aria-current={onUpload ? "page" : undefined}
          className={`flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[12.5px] focus-ring hover:bg-white/5 ${
            onUpload ? "bg-accent-dim text-text" : "text-accent-2"
          }`}
        >
          <Plus aria-hidden className="h-3.5 w-3.5 shrink-0" />
          {t("upload_source_files")}
        </button>
      </li>
      {files === null ? null : files.length === 0 ? (
        <li className="px-1.5 py-1 text-[12px] text-text-4">{t("source_tree_empty")}</li>
      ) : (
        files.map((name) => {
          const active = current === name;
          return (
            <li key={name}>
              <button
                type="button"
                onClick={() => navigate(`/source/${encodeURIComponent(name)}`)}
                aria-current={active ? "page" : undefined}
                title={name}
                className={`flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[12.5px] focus-ring hover:bg-white/5 ${
                  active ? "bg-accent-dim text-text" : "text-text-2"
                }`}
              >
                <FileText aria-hidden className="h-3.5 w-3.5 shrink-0 text-text-3" />
                <span className="min-w-0 flex-1 truncate">{name}</span>
              </button>
            </li>
          );
        })
      )}
    </ul>
  );
}
