/**
 * Spatial analysis of one episode (route `episodes/:episodeId/spatial`): two approved
 * shots, seen from opposite sides, become one evidence-only spatial candidate.
 */
import "./spatial.css";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "wouter";
import { ArrowLeft, ArrowLeftRight, ScanSearch } from "lucide-react";

import { WORKSPACE_ROUTE_EPISODES } from "@/app-routes";
import { useProjectsStore } from "@/stores/projects-store";

import {
  deriveSpatialFrame,
  executeSpatial,
  getSpatialRevision,
  listSpatialSources,
  type EvidenceClass,
  type SpatialAssertion,
  type SpatialSource,
} from "../api/spatialClient";

interface SpatialAnalysisPageProps {
  projectName: string;
  episode: number;
}

type Phase = "idle" | "frames" | "analyzing" | "done" | "error";

const CLASSES: readonly EvidenceClass[] = ["VISIBLE", "INFERRED", "GAP"];
const SCENE_MAX = 120;

interface PendingCommand {
  signature: string;
  commandId: string;
  candidateId: string;
}

function errorMessage(error: unknown): string | null {
  return error instanceof Error && error.message ? error.message : null;
}

export default function SpatialAnalysisPage({ projectName, episode }: SpatialAnalysisPageProps) {
  const { t } = useTranslation("dashboard");
  const title = useProjectsStore(
    (state) => state.currentProjectData?.episodes?.find((entry) => entry.episode === episode)?.title,
  );
  const [sources, setSources] = useState<SpatialSource[] | null>(null);
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [masterKey, setMasterKey] = useState("");
  const [reverseKey, setReverseKey] = useState("");
  const [frameIndex, setFrameIndex] = useState(0);
  const [sceneName, setSceneName] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [runError, setRunError] = useState<string | null>(null);
  const [assertions, setAssertions] = useState<SpatialAssertion[]>([]);
  const pending = useRef<PendingCommand | null>(null);
  const run = useRef<AbortController | null>(null);

  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listSpatialSources(projectName, episode, { signal: controller.signal }).then(
      (listed) => {
        if (controller.signal.aborted) return;
        setSources(listed);
        setMasterKey((key) => key || listed[0]?.artifact_key || "");
        setReverseKey((key) => key || listed[1]?.artifact_key || "");
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setSourcesError(errorMessage(error) ?? t("spatial_sources_failed"));
      },
    );
    return () => controller.abort();
  }, [projectName, episode, reloadToken, t]);

  useEffect(() => () => run.current?.abort(), []);

  const master = sources?.find((source) => source.artifact_key === masterKey);
  const reverse = sources?.find((source) => source.artifact_key === reverseKey);
  const trimmedScene = sceneName.trim();
  const busy = phase === "frames" || phase === "analyzing";
  const sameShot = Boolean(master && reverse && master.artifact_key === reverse.artifact_key);
  const canRun = Boolean(master && reverse) && !sameShot && trimmedScene.length > 0 && !busy;

  async function analyze() {
    if (!master || !reverse || !canRun) return;
    run.current?.abort();
    const controller = new AbortController();
    run.current = controller;
    const signature = JSON.stringify([master, reverse, frameIndex, trimmedScene]);
    if (pending.current?.signature !== signature) {
      const id = crypto.randomUUID();
      pending.current = { signature, commandId: `spatial:${id}`, candidateId: `spatial-ep${episode}-${id.slice(0, 8)}` };
    }
    const command = pending.current;
    setRunError(null);
    setPhase("frames");
    try {
      const [masterFrame, reverseFrame] = await Promise.all([
        deriveSpatialFrame(projectName, master, frameIndex, { signal: controller.signal }),
        deriveSpatialFrame(projectName, reverse, frameIndex, { signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      setPhase("analyzing");
      const head = await executeSpatial(
        projectName,
        {
          commandId: command.commandId,
          candidateId: command.candidateId,
          episode,
          sceneName: trimmedScene,
          master: { receipt_id: masterFrame.receipt_id, receipt_digest: masterFrame.receipt_digest },
          reverse: { receipt_id: reverseFrame.receipt_id, receipt_digest: reverseFrame.receipt_digest },
        },
        { signal: controller.signal },
      );
      const revision = await getSpatialRevision(projectName, head, { signal: controller.signal });
      if (controller.signal.aborted) return;
      pending.current = null;
      setAssertions(revision.payload.spatial.assertions);
      setPhase("done");
    } catch (error) {
      if (controller.signal.aborted) return;
      setRunError(errorMessage(error) ?? t("spatial_run_failed"));
      setPhase("error");
    }
  }

  const statusText =
    phase === "frames"
      ? t("spatial_status_frames")
      : phase === "analyzing"
        ? t("spatial_status_analyzing")
        : phase === "done"
          ? t("spatial_status_done", { count: assertions.length })
          : "";

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-bg">
      <header className="sp-header flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-hairline py-2.5">
        <Link
          href={`/${WORKSPACE_ROUTE_EPISODES}/${episode}`}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-text-3 hover:text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        >
          <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
          {t("spatial_back")}
        </Link>
        <div className="min-w-0">
          <p className="font-mono text-[10px] tracking-[0.18em] text-text-3">
            EPISODE {String(episode).padStart(2, "0")} · SPATIAL
          </p>
          <h1 className="truncate font-editorial text-xl leading-tight text-text">
            {title || t("spatial_title", { episode })}
          </h1>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl px-4 py-6">
        <p className="max-w-2xl text-sm text-text-2">{t("spatial_intro")}</p>

        {sourcesError ? (
          <div role="alert" className="mt-6 rounded-md border border-hairline-strong p-4 text-sm text-text-2">
            {sourcesError}
            <button
              type="button"
              onClick={() => {
                setSourcesError(null);
                setReloadToken((token) => token + 1);
              }}
              className="ml-3 rounded-md border border-hairline-strong px-2.5 py-1 text-xs hover:text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            >
              {t("spatial_retry")}
            </button>
          </div>
        ) : sources === null ? (
          <p role="status" className="mt-6 text-sm text-text-3">
            {t("spatial_sources_loading")}
          </p>
        ) : sources.length < 2 ? (
          <p className="mt-6 rounded-md border border-dashed border-hairline-strong p-4 text-sm text-text-2">
            {t("spatial_sources_empty")}
          </p>
        ) : (
          <form
            className="mt-6"
            onSubmit={(event) => {
              event.preventDefault();
              void analyze();
            }}
          >
            <div className="sp-pair">
              <ViewSlot
                kicker="MASTER"
                label={t("spatial_master_label")}
                value={masterKey}
                sources={sources}
                disabled={busy}
                onChange={setMasterKey}
              />
              <ArrowLeftRight aria-hidden className="sp-pair-glyph h-5 w-5 text-text-3" />
              <ViewSlot
                kicker="REVERSE"
                label={t("spatial_reverse_label")}
                value={reverseKey}
                sources={sources}
                disabled={busy}
                onChange={setReverseKey}
              />
            </div>
            {sameShot ? (
              <p className="mt-2 text-xs text-warn">{t("spatial_same_shot")}</p>
            ) : null}

            <div className="mt-5 grid gap-4 sm:grid-cols-[1fr_10rem]">
              <label className="block text-xs text-text-2">
                {t("spatial_scene_label")}
                <input
                  value={sceneName}
                  maxLength={SCENE_MAX}
                  disabled={busy}
                  onChange={(event) => setSceneName(event.target.value)}
                  placeholder={t("spatial_scene_placeholder")}
                  className="mt-1 block w-full rounded-md border border-hairline-strong bg-surface-2 px-3 py-2 text-sm text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                />
              </label>
              <label className="block text-xs text-text-2">
                {t("spatial_frame_label")}
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={frameIndex}
                  disabled={busy}
                  onChange={(event) => setFrameIndex(Math.max(0, Math.floor(Number(event.target.value) || 0)))}
                  className="mt-1 block w-full rounded-md border border-hairline-strong bg-surface-2 px-3 py-2 font-mono text-sm text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                />
              </label>
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={!canRun}
                className="sp-btn-accent inline-flex items-center gap-1.5 rounded-md px-3.5 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <ScanSearch aria-hidden className="h-4 w-4" />
                {busy ? t("spatial_analyzing") : t("spatial_analyze")}
              </button>
              <p role="status" aria-live="polite" className="text-xs text-text-3">
                {statusText}
              </p>
            </div>
            {runError ? (
              <p role="alert" className="mt-3 text-sm text-danger">
                {runError}
              </p>
            ) : null}
          </form>
        )}

        {phase === "done" ? <Findings assertions={assertions} /> : null}
      </main>
    </div>
  );
}

function ViewSlot(props: {
  kicker: string;
  label: string;
  value: string;
  sources: SpatialSource[];
  disabled: boolean;
  onChange: (key: string) => void;
}) {
  return (
    <label className="sp-slot block rounded-md border border-hairline-strong bg-surface-2 p-3">
      <span className="block font-mono text-[10px] tracking-[0.18em] text-text-3">{props.kicker}</span>
      <span className="mt-0.5 block text-xs text-text-2">{props.label}</span>
      <select
        value={props.value}
        disabled={props.disabled}
        onChange={(event) => props.onChange(event.target.value)}
        className="mt-2 block w-full rounded-md border border-hairline bg-bg px-2 py-1.5 text-sm text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
      >
        {props.sources.map((source) => (
          <option key={source.artifact_key} value={source.artifact_key}>
            {source.shot_id} · v{source.master_version}
          </option>
        ))}
      </select>
    </label>
  );
}

function Findings({ assertions }: { assertions: SpatialAssertion[] }) {
  const { t } = useTranslation("dashboard");
  return (
    <section aria-labelledby="sp-findings" className="mt-10">
      <h2 id="sp-findings" className="font-editorial text-lg text-text">
        {t("spatial_findings_title")}
      </h2>
      <p className="mt-1 max-w-2xl text-xs text-text-3">{t("spatial_findings_note")}</p>
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {CLASSES.map((evidenceClass) => {
          const items = assertions.filter((assertion) => assertion.evidence_class === evidenceClass);
          return (
            <section key={evidenceClass} aria-label={t(`spatial_class_${evidenceClass.toLowerCase()}`)}>
              <h3 className="flex items-baseline justify-between font-mono text-[10px] tracking-[0.18em] text-text-3">
                <span>{evidenceClass}</span>
                <span>{items.length}</span>
              </h3>
              <p className="mt-0.5 text-xs text-text-2">{t(`spatial_class_${evidenceClass.toLowerCase()}_hint`)}</p>
              {items.length === 0 ? (
                <p className="mt-3 text-xs text-text-3">{t("spatial_class_empty")}</p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {items.map((assertion) => (
                    <li key={assertion.assertion_id} className={`sp-finding sp-finding-${evidenceClass.toLowerCase()} rounded-md p-3`}>
                      <p className="text-sm text-text">{assertion.relation}</p>
                      <p className="mt-1 font-mono text-[10px] tracking-[0.12em] text-text-3">
                        {assertion.source_refs.join(" + ").toUpperCase()}
                        {assertion.confidence !== null ? ` · ${Math.round(assertion.confidence * 100)}%` : ""}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </div>
    </section>
  );
}
