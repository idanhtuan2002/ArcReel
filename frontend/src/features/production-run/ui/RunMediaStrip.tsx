import { useTranslation } from "react-i18next";
import { API } from "@/api";
import type { RunMedia } from "../api/types";

/**
 * The pictures and clips the current stage's finished tasks produced, newest first, like a job list's output
 * thumbnails. Files come from the owner's authenticated project file route; voice files are only counted.
 */
export function RunMediaStrip({ projectName, media }: { projectName: string; media: readonly RunMedia[] }) {
  const { t } = useTranslation("workflow");
  const visual = media.filter((item) => item.media_type !== "audio");
  const voices = media.length - visual.length;
  if (!media.length) return null;
  return (
    <figure className="m-0 space-y-1">
      <figcaption className="text-[11.5px]" style={{ color: "var(--color-text-3)" }}>
        {t("auto_media_made", { pictures: visual.length, voices })}
      </figcaption>
      {visual.length > 0 && (
        <ul aria-label={t("auto_media_list")} className="m-0 flex list-none gap-1.5 overflow-x-auto p-0 pb-1">
          {visual.map((item) => {
            const src = API.getFileUrl(projectName, item.file_path, item.version);
            const label = `${item.resource_id}${item.resource_type ? ` · ${item.resource_type}` : ""}`;
            return (
              <li key={item.task_id} className="shrink-0">
                <a href={src} target="_blank" rel="noreferrer" title={label}>
                  {item.media_type === "video" ? (
                     
                    <video
                      src={src}
                      muted
                      preload="metadata"
                      aria-label={label}
                      className="h-20 w-auto rounded"
                      style={{ border: "1px solid var(--color-hairline-strong)" }}
                    />
                  ) : (
                    <img
                      src={src}
                      alt={label}
                      loading="lazy"
                      className="h-20 w-auto rounded object-cover"
                      style={{ border: "1px solid var(--color-hairline-strong)" }}
                    />
                  )}
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </figure>
  );
}
