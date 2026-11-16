import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CircleHelp } from "lucide-react";

interface Props {
  /** What the hint explains, as the button's accessible name reads it ("Explain: Automatic production"). */
  topic: string;
  /** The explanation, one or two plain sentences. */
  children: React.ReactNode;
  /** Which side of the button the explanation opens toward. */
  align?: "left" | "right";
}

/**
 * A small "?" next to a term a filmmaker may not know; it opens a short explanation in place. Escape or a click
 * elsewhere closes it, and focus returns to the button.
 */
export function HelpHint({ topic, children, align = "left" }: Props) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const wrapper = useRef<HTMLSpanElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (wrapper.current && !wrapper.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <span ref={wrapper} className="relative inline-flex align-middle">
      <button
        ref={button}
        type="button"
        onClick={(event) => {
          // The hint often sits inside a summary or a clickable row: it must not toggle or open them too.
          event.preventDefault();
          event.stopPropagation();
          setOpen((value) => !value);
        }}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={t("help_about", { topic })}
        title={t("help_about", { topic })}
        className="focus-ring grid h-5 w-5 place-items-center rounded-full transition-colors hover:text-[var(--color-text)]"
        style={{ color: "var(--color-text-3)" }}
      >
        <CircleHelp aria-hidden className="h-3.5 w-3.5" />
      </button>
      {open && (
        <span
          id={panelId}
          role="note"
          className={`absolute top-6 z-30 block w-72 rounded-lg p-3 text-left text-[12px] font-normal normal-case leading-[1.6] tracking-normal ${
            align === "right" ? "right-0" : "left-0"
          }`}
          style={{
            background: "var(--color-surface-2)",
            border: "1px solid var(--color-hairline)",
            color: "var(--color-text-2)",
            boxShadow: "0 12px 32px -12px oklch(0 0 0 / 0.6)",
          }}
        >
          {children}
        </span>
      )}
    </span>
  );
}
