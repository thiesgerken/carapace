"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Plus } from "lucide-react";
import { cn } from "@/lib/utils";

interface NewSessionButtonProps {
  onCreate: (unattended?: boolean) => void;
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

  function handleCreate(unattended = false) {
    setOpen(false);
    onCreate(unattended);
  }

  return (
    <div
      ref={rootRef}
      className={cn("relative", fullWidth && "w-full", className)}
    >
      <div className="flex w-full items-stretch">
        <button
          onClick={() => handleCreate(false)}
          disabled={disabled}
          className={cn(
            "flex items-center gap-2 rounded-l-lg border border-border px-3 py-2 text-sm transition-colors",
            "bg-background hover:bg-muted",
            "disabled:opacity-50",
            fullWidth && "flex-1 justify-start",
          )}
        >
          <Plus className="h-4 w-4" />
          New session
        </button>
        <button
          onClick={() => setOpen((current) => !current)}
          disabled={disabled}
          aria-label="Choose session mode"
          aria-expanded={open}
          aria-haspopup="menu"
          className={cn(
            "rounded-r-lg border border-l-0 border-border px-2.5 transition-colors",
            "bg-background hover:bg-muted",
            "disabled:opacity-50",
          )}
        >
          <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
        </button>
      </div>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-1 min-w-72 rounded-xl border border-border bg-background p-1.5 shadow-lg"
        >
          <button
            onClick={() => handleCreate(false)}
            className="flex w-full flex-col rounded-lg px-3 py-2 text-left transition-colors hover:bg-muted"
          >
            <span className="text-sm font-medium text-foreground">Attended</span>
            <span className="text-xs text-muted-foreground">
              Chat normally and approve escalations in place.
            </span>
          </button>
          <button
            onClick={() => handleCreate(true)}
            className="flex w-full flex-col rounded-lg px-3 py-2 text-left transition-colors hover:bg-muted"
          >
            <span className="text-sm font-medium text-foreground">Unattended</span>
            <span className="text-xs text-muted-foreground">
              Runs on its own with no user approval path.
            </span>
          </button>
        </div>
      ) : null}
    </div>
  );
}
