import { cn } from "@/lib/utils";

/** The chat's "still running" mark: braille dots cycling in CSS (`.braille-spinner` in globals.css). */
export function BrailleSpinner({ className }: { className?: string }) {
  return <span aria-hidden="true" className={cn("braille-spinner", className)} />;
}
