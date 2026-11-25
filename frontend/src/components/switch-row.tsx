"use client";

import { cn } from "@/lib/utils";

type SwitchRowProps = {
  checked: boolean;
  label: string;
  description?: string;
  /** Tooltip, for a compact row that leaves the description out. */
  title?: string;
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
  title,
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
      title={title}
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
        <span className="block text-sm font-medium text-foreground">{label}</span>
        {description ? (
          <span className="mt-0.5 block text-sm text-muted-foreground">{description}</span>
        ) : null}
      </span>
    </button>
  );
}
