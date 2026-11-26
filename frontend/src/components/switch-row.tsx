"use client";

import { cn } from "@/lib/utils";

type SwitchRowProps = {
  checked: boolean;
  label: string;
  description?: string;
  disabled?: boolean;
  onCheckedChange: (checked: boolean) => void;
  className?: string;
};

export function SwitchRow({
  checked,
  label,
  description,
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
          checked
            ? "border-primary bg-primary"
            : "border-border bg-muted",
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
