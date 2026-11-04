import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { SEVERITY_TONES } from "@/utils/severity-tone";
import { getProductionRunReport } from "../api/productionRunClient";
import type { ReviewScore, RunReport } from "../api/types";

const SCORES: readonly ReviewScore[] = ["story", "visual", "audio", "continuity", "pacing"];

interface Props {
  projectName: string;
  runId: string;
  /** The run's version: the report is read again only when the run moved. */
  version: number;
}

/**
 * What the run decided on its own, read from the server: each reviewer's scores and findings per episode, and the
 * story exceptions the automatic commit accepted. Both are collapsed; a run that has not reached them shows nothing.
 */
export function RunReportDetails({ projectName, runId, version }: Props) {
  const { t } = useTranslation("workflow");
  const [report, setReport] = useState<RunReport | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getProductionRunReport(projectName, runId, { signal: controller.signal })
      .then((loaded) => {
        if (!controller.signal.aborted) setReport(loaded);
      })
      .catch(() => {
        // The report is supplementary; the run panel stays usable without it.
      });
    return () => controller.abort();
  }, [projectName, runId, version]);

  if (!report || report.run_id !== runId) return null;
  return (
    <div className="space-y-1.5 text-[12px]">
      {report.quality.length > 0 && (
        <details>
          <summary className="cursor-pointer" style={{ color: "var(--color-text-2)" }}>
            {t("auto_report_quality")}
          </summary>
          <div className="mt-1 space-y-2">
            {report.quality.map((episode) => (
              <div key={episode.target}>
                <p style={{ color: "var(--color-text-2)" }}>
                  {t("auto_report_episode", { episode: Number(episode.target.split(":")[1]) })}
                </p>
                <ul className="m-0 list-none space-y-1 p-0">
                  {episode.reviews.map((review) => (
                    <li key={review.role}>
                      <span style={{ color: review.accepted ? "var(--color-accent-2)" : SEVERITY_TONES.warnings.color }}>
                        {review.accepted ? t("auto_report_accepted") : t("auto_report_rejected")}
                      </span>{" "}
                      <span className="font-mono text-[11px]" style={{ color: "var(--color-text-3)" }}>
                        {review.model_identity.split("@")[0]}
                      </span>
                      <span className="ml-2" style={{ color: "var(--color-text-2)" }}>
                        {SCORES.map((score) =>
                          t("auto_report_score", { name: t(`auto_score_${score}`), value: review.scores[score] ?? "–" }),
                        ).join(" · ")}
                      </span>
                      {review.findings.length > 0 && (
                        <ul className="m-0 mt-0.5 list-disc space-y-0.5 pl-5" style={{ color: "var(--color-text-3)" }}>
                          {review.findings.map((finding, index) => (
                            <li key={index}>
                              {finding.severity} · {finding.code}
                              {finding.detail ? `: ${finding.detail}` : ""}
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </details>
      )}
      {report.story_exceptions.length > 0 && (
        <details>
          <summary className="cursor-pointer" style={{ color: SEVERITY_TONES.warnings.color }}>
            {t("auto_report_story_exceptions", { count: report.story_exceptions.length })}
          </summary>
          <ul className="m-0 mt-1 list-none space-y-1.5 p-0">
            {report.story_exceptions.map((finding, index) => (
              <li key={index} style={{ color: "var(--color-text-3)" }}>
                <span className="font-mono text-[11px]" style={{ color: "var(--color-text-2)" }}>
                  {finding.node_id}
                </span>{" "}
                {finding.message}
                {finding.quote && <q className="ml-1 italic">{finding.quote}</q>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
