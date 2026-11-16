import type { ReactNode } from "react";

/** A small labelled value in the debug view's stat rows. */
export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{label}</span>
      <span className="text-sm">{value}</span>
    </div>
  );
}
