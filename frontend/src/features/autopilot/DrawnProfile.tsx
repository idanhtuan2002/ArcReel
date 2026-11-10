import { useTranslation } from "react-i18next";
import { Sparkles } from "lucide-react";

import type { StoryProfile } from "@/types/project";

const GENRES = [
  "family",
  "mystery",
  "horror",
  "romance",
  "action",
  "fantasy",
  "scifi",
  "comedy",
  "historical",
  "school",
] as const;

/** ADR-0125: what an automatic story chose for itself — its title, idea, genre, tone, readers and length. */
export function DrawnProfile({ profile }: { profile: StoryProfile }) {
  const { t } = useTranslation("dashboard");
  const genre = (GENRES as readonly string[]).includes(profile.genre_pack)
    ? t(`ap_genre_${profile.genre_pack}`)
    : profile.genre_pack;
  const defaulted = new Set(profile.defaulted ?? []);
  const chips: [string, string, string][] = [
    ["genre_pack", t("ap_profile_genre"), genre],
    ["tone", t("ap_profile_tone"), profile.tone],
    ["audience", t("ap_profile_audience"), profile.audience],
    ["book_chapters", t("ap_profile_length"), t("ap_profile_chapters", { n: profile.book_chapters })],
  ];
  return (
    <section aria-label={t("ap_profile_title")} className="rounded-md border border-hairline px-3 py-2">
      <p className="flex items-center gap-1.5 text-[12px] text-text-3">
        <Sparkles aria-hidden className="h-3.5 w-3.5" />
        {t("ap_profile_title")}
      </p>
      <p className="mt-1 text-[13px] font-medium text-text">{profile.title}</p>
      <p className="mt-0.5 text-[12.5px] leading-relaxed text-text-2">{profile.idea}</p>
      <ul className="mt-2 flex flex-wrap gap-1.5">
        {chips.map(([key, label, value]) => (
          <li
            key={key}
            title={defaulted.has(key) ? t("ap_profile_defaulted") : undefined}
            className="rounded-full border border-hairline px-2 py-0.5 text-[11.5px] text-text-2"
          >
            <span className="text-text-3">{label}: </span>
            {value}
            {defaulted.has(key) ? <span className="text-text-3"> *</span> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
