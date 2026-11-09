import { useState } from "react";
import { useTranslation } from "react-i18next";
import { translateStory, type TranslationLanguage } from "../api/storyClient";

const LANGUAGES: TranslationLanguage[] = ["en", "fr", "es", "de", "zh", "ja", "ko"];

/** Translate the project's story into another language (ADR-0120); the result lands under translations/. */
export function TranslateStory({ projectName }: { projectName: string }) {
  const { t } = useTranslation("dashboard");
  const [language, setLanguage] = useState<TranslationLanguage>("en");
  const [state, setState] = useState<"idle" | "busy" | "queued" | "failed">("idle");
  const start = async () => {
    setState("busy");
    try {
      await translateStory(projectName, language);
      setState("queued");
    } catch {
      setState("failed");
    }
  };
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-text-2">
      <label className="flex items-center gap-1.5">
        {t("story_translate_label")}
        <select
          className="sa-input w-auto"
          value={language}
          onChange={(event) => setLanguage(event.target.value as TranslationLanguage)}
        >
          {LANGUAGES.map((code) => (
            <option key={code} value={code}>
              {t(`story_language_${code}`)}
            </option>
          ))}
        </select>
      </label>
      <button type="button" className="sa-btn" disabled={state === "busy"} onClick={() => void start()}>
        {t("story_translate")}
      </button>
      {state === "queued" ? <span role="status">{t("story_translate_queued")}</span> : null}
      {state === "failed" ? <span role="alert">{t("story_translate_failed")}</span> : null}
    </div>
  );
}
