"use client";

import { useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

const FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";
const FRAME_MS = 80;

// One wall-clock ticker for every spinner: a spinner that remounts mid-stream shows the same frame
// as the others instead of starting over, and many running rows still cost one interval.
const listeners = new Set<() => void>();
let ticker: ReturnType<typeof setInterval> | undefined;

function subscribe(onTick: () => void): () => void {
  listeners.add(onTick);
  ticker ??= setInterval(() => listeners.forEach((listener) => listener()), FRAME_MS);
  return () => {
    listeners.delete(onTick);
    if (listeners.size === 0) {
      clearInterval(ticker);
      ticker = undefined;
    }
  };
}

const currentFrame = () => FRAMES[Math.floor(Date.now() / FRAME_MS) % FRAMES.length];
const firstFrame = () => FRAMES[0];

/** The chat's "still running" mark: braille dots cycling every 80 ms. */
export function BrailleSpinner({ className }: { className?: string }) {
  const frame = useSyncExternalStore(subscribe, currentFrame, firstFrame);
  // The frame reaches the screen through CSS (`.braille-spinner` in globals.css): that keeps it out
  // of the text content and lets reduced motion pin it.
  return <span aria-hidden="true" data-frame={frame} className={cn("braille-spinner", className)} />;
}
