import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API, type ApprovedDeliverable, type GateDecision, type GateHistory } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { errMsg } from "@/utils/async";

/** Trigger a browser download through a hidden anchor, without opening a blank tab. */
function triggerBrowserDownload(url: string) {
  const a = document.createElement("a");
  a.href = url;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

interface GateApprovalPanelProps {
  projectName: string;
}

/**
 * ADR-0089's four mandatory V1 Human Gates. Greenlight (A) and Publish
 * Approval (D) get a real one-click approve action here, backed by
 * server/routers/gates.py's new, small append-only tables. Narrative Lock
 * (B) and Final Cut (C) are approved through the gate API: each requires a
 * full domain command (a screenplay admission / a rendered candidate) with no
 * simplified "pending items to review" surface yet. Final Cut lists the current
 * approved finals (ADR-0090 O2a): each downloads through the download-token
 * route and can fill Publish Approval's digest.
 */
export function GateApprovalPanel({ projectName }: GateApprovalPanelProps) {
  const { t } = useTranslation("dashboard");
  const pushToast = useAppStore((s) => s.pushToast);
  const [history, setHistory] = useState<GateHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [sourceDigest, setSourceDigest] = useState("");
  const [deliverableDigest, setDeliverableDigest] = useState("");
  const [platform, setPlatform] = useState("");
  const [visibility, setVisibility] = useState("");
  const [busyAction, setBusyAction] = useState<"greenlight" | "publish" | null>(null);
  const [deliverables, setDeliverables] = useState<ApprovedDeliverable[]>([]);

  async function loadHistory() {
    try {
      const result = await API.getGateHistory(projectName);
      setHistory(result);
    } catch (err) {
      pushToast(t("gate_action_failed", { message: errMsg(err) }), "error");
    } finally {
      setLoading(false);
    }
  }

  async function loadDeliverables(signal: AbortSignal) {
    try {
      const result = await API.requestDeliverableToken(projectName, { signal });
      if (signal.aborted) return;
      setDeliverables(result.deliverables);
    } catch (err) {
      if (signal.aborted) return;
      pushToast(t("gate_action_failed", { message: errMsg(err) }), "error");
    }
  }

  async function handleDownload(deliverable: ApprovedDeliverable) {
    try {
      const { download_token } = await API.requestDeliverableToken(projectName);
      triggerBrowserDownload(API.getDeliverableDownloadUrl(projectName, download_token, deliverable.sha256));
    } catch (err) {
      pushToast(t("gate_deliverable_download_failed", { message: errMsg(err) }), "error");
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 挂载时拉取服务端 gate 历史，属 React 官方认可的 effect 用途（与外部系统同步）；setState 发生在 await 之后的微任务续行里，不是 effect 体内的同步调用，与 VersionTimeMachine.tsx 的 loadVersions 挂载拉取同一模式
    void loadHistory();
    const controller = new AbortController();
    void loadDeliverables(controller.signal);
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loadHistory 是组件内普通函数，无法稳定化；加入 deps 会导致每次渲染重复触发
  }, [projectName]);

  async function handleGreenlight() {
    if (!sourceDigest.trim()) return;
    setBusyAction("greenlight");
    try {
      await API.greenlightProject(projectName, { source_digest: sourceDigest.trim(), action: "GREENLIGHT" });
      pushToast(t("gate_greenlight_success"), "success");
      setSourceDigest("");
      await loadHistory();
    } catch (err) {
      pushToast(t("gate_action_failed", { message: errMsg(err) }), "error");
    } finally {
      setBusyAction(null);
    }
  }

  async function handlePublishApproval() {
    if (!deliverableDigest.trim() || !platform.trim() || !visibility.trim()) return;
    setBusyAction("publish");
    try {
      await API.publishApproval(projectName, {
        deliverable_digest: deliverableDigest.trim(),
        platform: platform.trim(),
        visibility: visibility.trim(),
        action: "APPROVE_PUBLISH",
      });
      pushToast(t("gate_publish_approval_success"), "success");
      setDeliverableDigest("");
      setPlatform("");
      setVisibility("");
      await loadHistory();
    } catch (err) {
      pushToast(t("gate_action_failed", { message: errMsg(err) }), "error");
    } finally {
      setBusyAction(null);
    }
  }

  function latest(decisions: GateDecision[] | undefined): GateDecision | null {
    if (!decisions || decisions.length === 0) return null;
    return decisions[decisions.length - 1];
  }

  const latestGreenlight = latest(history?.greenlight);
  const latestPublish = latest(history?.publish_approval);

  return (
    <div className="flex flex-col gap-4 text-[13px] text-text">
      <div className="flex flex-col gap-2 rounded-[8px] border border-hairline-soft p-3">
        <div className="font-semibold">{t("gate_greenlight_label")}</div>
        <div className="text-[12px] text-text-3">
          {latestGreenlight
            ? t("gate_status_history_count", { count: history?.greenlight.length ?? 0 })
            : t("gate_status_not_yet_decided")}
        </div>
        <input
          className="rounded-[6px] border border-hairline bg-transparent px-2 py-1 text-[12px]"
          placeholder={t("gate_source_digest_label")}
          value={sourceDigest}
          onChange={(e) => setSourceDigest(e.target.value)}
          disabled={busyAction !== null}
        />
        <button
          type="button"
          className="self-start rounded-[6px] border border-hairline px-3 py-1 text-[12px] disabled:opacity-50"
          onClick={() => void handleGreenlight()}
          disabled={busyAction !== null || !sourceDigest.trim()}
        >
          {t("gate_approve_button")}
        </button>
      </div>

      <div className="flex flex-col gap-2 rounded-[8px] border border-hairline-soft p-3">
        <div className="font-semibold">{t("gate_narrative_lock_label")}</div>
        <div className="text-[12px] text-text-3">{t("gate_managed_via_api_hint")}</div>
      </div>

      <div className="flex flex-col gap-2 rounded-[8px] border border-hairline-soft p-3">
        <div className="font-semibold">{t("gate_final_cut_label")}</div>
        {deliverables.length === 0 ? (
          <div className="text-[12px] text-text-3">{t("gate_deliverables_empty")}</div>
        ) : (
          deliverables.map((deliverable) => (
            <div key={deliverable.sha256} className="flex flex-wrap items-center gap-2 text-[12px]">
              <span>{t("gate_deliverable_row", { episode: deliverable.episode, target: deliverable.target_ref })}</span>
              <code className="text-text-3" title={deliverable.sha256}>
                {deliverable.sha256.slice(0, 19)}…
              </code>
              <button
                type="button"
                className="rounded-[6px] border border-hairline px-2 py-0.5"
                onClick={() => void handleDownload(deliverable)}
              >
                {t("gate_deliverable_download")}
              </button>
              <button
                type="button"
                className="rounded-[6px] border border-hairline px-2 py-0.5"
                onClick={() => setDeliverableDigest(deliverable.sha256)}
                disabled={busyAction !== null}
              >
                {t("gate_deliverable_use_for_publish")}
              </button>
            </div>
          ))
        )}
      </div>

      <div className="flex flex-col gap-2 rounded-[8px] border border-hairline-soft p-3">
        <div className="font-semibold">{t("gate_publish_approval_label")}</div>
        <div className="text-[12px] text-text-3">
          {latestPublish
            ? t("gate_status_history_count", { count: history?.publish_approval.length ?? 0 })
            : t("gate_status_not_yet_decided")}
        </div>
        <input
          className="rounded-[6px] border border-hairline bg-transparent px-2 py-1 text-[12px]"
          placeholder={t("gate_deliverable_digest_label")}
          value={deliverableDigest}
          onChange={(e) => setDeliverableDigest(e.target.value)}
          disabled={busyAction !== null}
        />
        <input
          className="rounded-[6px] border border-hairline bg-transparent px-2 py-1 text-[12px]"
          placeholder={t("gate_platform_label")}
          value={platform}
          onChange={(e) => setPlatform(e.target.value)}
          disabled={busyAction !== null}
        />
        <input
          className="rounded-[6px] border border-hairline bg-transparent px-2 py-1 text-[12px]"
          placeholder={t("gate_visibility_label")}
          value={visibility}
          onChange={(e) => setVisibility(e.target.value)}
          disabled={busyAction !== null}
        />
        <button
          type="button"
          className="self-start rounded-[6px] border border-hairline px-3 py-1 text-[12px] disabled:opacity-50"
          onClick={() => void handlePublishApproval()}
          disabled={busyAction !== null || !deliverableDigest.trim() || !platform.trim() || !visibility.trim()}
        >
          {t("gate_approve_button")}
        </button>
      </div>

      {loading ? <div className="text-[12px] text-text-3">{t("gate_loading")}</div> : null}
    </div>
  );
}
