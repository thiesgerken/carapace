"use client";

import { useEffect, useRef, useState } from "react";

/** *value*, once it held still for *delayMs*, but never later than *maxWaitMs* after it first changed. */
export function useDebounced<T>(value: T, delayMs: number, maxWaitMs: number): T {
  const [settled, setSettled] = useState(value);
  const pendingSince = useRef<number | null>(null);

  useEffect(() => {
    if (Object.is(value, settled)) {
      pendingSince.current = null;
      return;
    }
    pendingSince.current ??= Date.now();
    const id = setTimeout(() => setSettled(value), Math.max(0, Math.min(delayMs, pendingSince.current + maxWaitMs - Date.now())));
    return () => clearTimeout(id);
  }, [value, settled, delayMs, maxWaitMs]);

  return settled;
}
