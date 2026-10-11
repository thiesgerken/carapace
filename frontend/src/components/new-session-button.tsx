"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { SESSION_OPTION_ORDER, SessionOptionTiles, type SessionOptionKey } from "@/components/session-option-tiles";
import { cn } from "@/lib/utils";

export interface NewSessionOptions {
  private?: boolean;
  unattended?: boolean;
  ask_mode?: boolean;
  yolo_mode?: boolean;
}

/** Ask and YOLO mode exclude each other, so turning one on turns the other off. */
function withOption(options: NewSessionOptions, key: SessionOptionKey, checked: boolean): NewSessionOptions {
  const next = { ...options, [key]: checked };
  if (key === "ask_mode" && checked) next.yolo_mode = false;
  if (key === "yolo_mode" && checked) next.ask_mode = false;
  return next;
}

interface NewSessionButtonProps {
  onCreate: (options?: NewSessionOptions) => void;
  disabled?: boolean;
  fullWidth?: boolean;
  className?: string;
}

export function NewSessionButton({
  onCreate,
  disabled = false,
  fullWidth = false,
  className,
}: NewSessionButtonProps) {
  const t = useTranslations("newSessionButton");
  const [options, setOptions] = useState<NewSessionOptions>({});

  return (
    <div className={cn("flex items-stretch", fullWidth && "w-full", className)}>
      <button
        onClick={() => onCreate(options)}
        disabled={disabled}
        className={cn(
          "flex items-center gap-2 rounded-l-lg border border-border px-3 py-2 text-sm transition-colors",
          "bg-background hover:bg-muted",
          "disabled:opacity-50",
          fullWidth && "flex-1 justify-start",
        )}
      >
        <Plus className="h-4 w-4" />
        {t("label")}
      </button>
      <SessionOptionsDropdown
        options={options}
        onChange={setOptions}
        disabled={disabled}
        className="rounded-r-lg border-l-0"
      />
    </div>
  );
}

/** The ▾ next to a new-session control: picks private, ask, YOLO and unattended for the session it creates. */
export function SessionOptionsDropdown({
  options,
  onChange,
  disabled = false,
  className,
}: {
  options: NewSessionOptions;
  onChange: (options: NewSessionOptions) => void;
  disabled?: boolean;
  className?: string;
}) {
  const t = useTranslations("newSessionButton");
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative flex">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        disabled={disabled}
        aria-label={t("chooseOptions")}
        aria-expanded={open}
        aria-haspopup="dialog"
        className={cn(
          "border border-border px-2.5 transition-colors",
          "bg-background hover:bg-muted",
          "disabled:opacity-50",
          className,
        )}
      >
        <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
      </button>

      {open ? (
        <div
          role="dialog"
          aria-label={t("chooseOptions")}
          className="absolute right-0 top-full z-20 mt-1 min-w-80 rounded-xl border border-border bg-background p-3 shadow-lg"
        >
          <SessionOptionTiles
            items={SESSION_OPTION_ORDER.map((key) => ({
              key,
              active: !!options[key],
              onClick: () => onChange(withOption(options, key, !options[key])),
            }))}
          />
        </div>
      ) : null}
    </div>
  );
}
