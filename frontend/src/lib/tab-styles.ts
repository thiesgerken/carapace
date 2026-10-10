import { cn } from "@/lib/utils";

export const tabbedPageClassName = "flex min-h-0 flex-1 flex-col overflow-hidden bg-[radial-gradient(circle_at_top_left,_color-mix(in_oklch,var(--accent)_55%,transparent),transparent_35%),linear-gradient(180deg,color-mix(in_oklch,var(--background)_96%,var(--muted))_0%,var(--background)_100%)]";

export const tabLinkClassName = (selected: boolean): string => cn(
  "rounded-t-lg border border-b-0 px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
  selected
    ? "relative z-10 -mb-px border-border bg-background text-foreground"
    : "border-transparent text-muted-foreground hover:border-border/60 hover:bg-background/70 hover:text-foreground",
);
