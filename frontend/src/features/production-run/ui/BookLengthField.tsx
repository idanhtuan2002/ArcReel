import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";

/** A long story written part by part (ADR-0116); ``null`` is a three-chapter story. */
export interface BookLength {
  chapters: number;
  partChapters: number;
  chapterSyllables: number;
}

export const BOOK_DEFAULT: BookLength = { chapters: 30, partChapters: 5, chapterSyllables: 3000 };

const BOUNDS = {
  chapters: [6, 120],
  partChapters: [3, 6],
  chapterSyllables: [2000, 5000],
} as const;

export function bookLengthValid(book: BookLength | null): boolean {
  return (
    book === null ||
    (Object.keys(BOUNDS) as (keyof BookLength)[]).every((key) => {
      const [low, high] = BOUNDS[key];
      return Number.isInteger(book[key]) && book[key] >= low && book[key] <= high;
    })
  );
}

/** The request field a brief carries for a book. */
export function bookSpec(book: BookLength | null) {
  return book === null
    ? {}
    : {
        book: {
          chapters: book.chapters,
          part_chapters: book.partChapters,
          chapter_syllables: book.chapterSyllables,
        },
      };
}

export interface StoryBookProgress {
  spec: { chapters: number; part_chapters: number; chapter_syllables: number };
  parts_done: number;
  parts_total: number;
}

/** The project's book, if it has one: how many parts are committed and handed to video. */
export function useStoryBook(projectName: string): StoryBookProgress | null {
  const [book, setBook] = useState<StoryBookProgress | null>(null);
  useEffect(() => {
    let live = true;
    void API.request<{ book: StoryBookProgress | null }>(
      `/projects/${encodeURIComponent(projectName)}/story-book`,
    )
      .then((result) => {
        if (live) setBook(result?.book ?? null);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [projectName]);
  return book;
}

interface Props {
  value: BookLength | null;
  onChange: (value: BookLength | null) => void;
  /** Only the chapter count (the run panel); the story page also sets part size and chapter length. */
  compact?: boolean;
}

const INPUT_CLS = "focus-ring w-20 rounded-md px-1.5 py-0.5 tabular-nums";
const INPUT_STYLE = { border: "1px solid var(--color-hairline-strong)", background: "transparent" };

/** Choose a three-chapter story or a book of many chapters written part by part. */
export function BookLengthField({ value, onChange, compact = false }: Props) {
  const { t } = useTranslation("workflow");
  const id = useId();
  const fields: (keyof BookLength)[] = compact ? ["chapters"] : ["chapters", "partChapters", "chapterSyllables"];
  return (
    <div className="space-y-1.5 text-[12px]" style={{ color: "var(--color-text-2)" }}>
      <label className="flex items-center gap-1.5">
        <input
          type="checkbox"
          checked={value !== null}
          onChange={(event) => onChange(event.target.checked ? BOOK_DEFAULT : null)}
        />
        {t("book_enable")}
      </label>
      {value !== null && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            {fields.map((key) => (
              <label key={key} htmlFor={`${id}-${key}`} className="flex items-center gap-1.5">
                {t(`book_${key}`)}
                <input
                  id={`${id}-${key}`}
                  type="number"
                  min={BOUNDS[key][0]}
                  max={BOUNDS[key][1]}
                  step={key === "chapterSyllables" ? 500 : 1}
                  value={value[key]}
                  onChange={(event) => onChange({ ...value, [key]: Number(event.target.value) })}
                  className={INPUT_CLS}
                  style={INPUT_STYLE}
                />
              </label>
            ))}
          </div>
          <p style={{ color: "var(--color-text-3)" }}>
            {t("book_hint", { parts: Math.ceil(value.chapters / value.partChapters) })}
          </p>
        </>
      )}
    </div>
  );
}

/** What a continuation of this project writes: the book's next part, or a free continuation. */
export function BookContinuationNote({ book }: { book: StoryBookProgress | null }) {
  const { t } = useTranslation("workflow");
  if (book === null) return null;
  const left = book.parts_done < book.parts_total;
  return (
    <p className="text-[12px]" style={{ color: "var(--color-text-3)" }}>
      {left
        ? t("book_next_part", { part: book.parts_done + 1, total: book.parts_total })
        : t("book_done", { total: book.parts_total })}
    </p>
  );
}
