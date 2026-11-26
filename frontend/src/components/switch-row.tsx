"use client";

import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

type SwitchRowProps = {
  checked: boolean;
  label: string;
  description?: string;
  /** Shown before the label, tinted like the track: muted when off. */
  icon?: LucideIcon;
  /** The checked state lowers a safeguard (YOLO), so it warns instead of reading as a plain selection. */
  warning?: boolean;
  disabled?: boolean;
  onCheckedChange: (checked: boolean) => void;
  className?: string;
};

export function SwitchRow({
  checked,
  label,
  description,
  icon: Icon,
  warning = false,
  disabled = false,
  onCheckedChange,
  className,
}: SwitchRowProps) {
  const hasDescription = Boolean(description);

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "flex w-full gap-3 rounded-xl p-1 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-ring/30 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
        hasDescription ? "items-start" : "items-center",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors",
          hasDescription && "mt-0.5",
          !checked ? "border-border bg-muted" : warning ? "border-warning bg-warning" : "border-primary bg-primary",
        )}
      >
        <span
          className={cn(
            "inline-block h-5 w-5 rounded-full bg-background shadow-sm transition-transform",
            checked ? "translate-x-6" : "translate-x-1",
          )}
        />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5 text-sm font-medium text-foreground">
          {Icon ? (
            <Icon
              aria-hidden="true"
              className={cn("h-4 w-4 shrink-0", !checked ? "text-muted-foreground" : warning ? "text-warning" : "text-primary")}
            />
          ) : null}
          {label}
        </span>
        {description ? (
          <span className="mt-0.5 block text-sm text-muted-foreground">{description}</span>
        ) : null}
      </span>
    </button>
  );
}
