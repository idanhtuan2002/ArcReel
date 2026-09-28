import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { errMsg } from "@/utils/async";

interface ProjectAdmissionToggleProps {
  projectName: string;
}

/**
 * ADR-0094: pausing a project stops the worker from claiming its queued generation tasks;
 * running tasks finish. The setting takes effect at the worker's next claim cycle.
 */
export function ProjectAdmissionToggle({ projectName }: ProjectAdmissionToggleProps) {
  const { t } = useTranslation("dashboard");
  const pushToast = useAppStore((s) => s.pushToast);
  const [paused, setPaused] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const admission = await API.getAdmission({ signal: controller.signal });
        if (controller.signal.aborted) return;
        setPaused(admission.paused.includes(projectName));
      } catch (err) {
        if (controller.signal.aborted) return;
        pushToast(t("admission_update_failed", { message: errMsg(err) }), "error");
      }
    })();
    return () => controller.abort();
  }, [projectName, pushToast, t]);

  async function handleChange(next: boolean) {
    setSaving(true);
    try {
      const result = await API.setProjectPaused(projectName, next);
      setPaused(result.paused);
    } catch (err) {
      pushToast(t("admission_update_failed", { message: errMsg(err) }), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex items-start gap-2 text-[13px] text-text">
      <input
        id="project-admission-paused"
        type="checkbox"
        checked={paused ?? false}
        disabled={paused === null || saving}
        onChange={(e) => void handleChange(e.target.checked)}
        className="mt-0.5 h-3.5 w-3.5 rounded border-hairline bg-bg-grad-a accent-[var(--color-accent)] disabled:cursor-not-allowed enabled:cursor-pointer"
      />
      <label htmlFor="project-admission-paused" className="cursor-pointer">
        {t("admission_paused_label")}
      </label>
    </div>
  );
}
