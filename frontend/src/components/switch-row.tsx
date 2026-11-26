"use client";

import { cn } from "@/lib/utils";

/**
 * The switch's track and knob, for a `role="switch"` button that brings its own label. Off is a grey track
 * with a light knob in both themes: a background-coloured knob on a muted track vanishes in dark mode.
 */
export function SwitchTrack({
  checked,
  warning = false,
  small = false,
  className,
}: {
  checked: boolean;
  /** The checked state lowers a safeguard, so it warns instead of reading as a plain selection. */
  warning?: boolean;
  small?: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative inline-flex shrink-0 items-center rounded-full transition-colors",
        small ? "h-5 w-9" : "h-7 w-12",
        !checked ? "bg-muted-foreground/30" : warning ? "bg-warning" : "bg-primary",
        className,
      )}
    >
      <span
        className={cn(
          "inline-block rounded-full bg-background shadow-sm transition-transform dark:bg-foreground",
          small ? "h-4 w-4" : "h-5 w-5",
          small ? (checked ? "translate-x-[1.125rem]" : "translate-x-0.5") : checked ? "translate-x-6" : "translate-x-1",
        )}
      />
    </span>
  );
}

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
      <SwitchTrack checked={checked} className={cn(hasDescription && "mt-0.5")} />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-foreground">{label}</span>
        {description ? (
          <span className="mt-0.5 block text-sm text-muted-foreground">{description}</span>
        ) : null}
      </span>
    </button>
  );
}
