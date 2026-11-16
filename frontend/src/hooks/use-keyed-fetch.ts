"use client";

import { useEffect, useState } from "react";

export type Outcome<T> = { key: string; value: T } | { key: string; error: string };

/**
 * What *load* returned for the latest *key* (null loads nothing), refetched whenever *key* changes.
 * The previous key's outcome keeps showing while the next one loads; callers drop it by its key when it no longer fits.
 */
export function useKeyedFetch<T>(key: string | null, load: () => Promise<T>): Outcome<T> | null {
  const [outcome, setOutcome] = useState<Outcome<T> | null>(null);

  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    load()
      .then((value) => {
        if (!cancelled) setOutcome({ key, value });
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setOutcome({ key, error: loadError instanceof Error ? loadError.message : String(loadError) });
      });
    return () => {
      cancelled = true;
    };
  }, [key, load]);

  return outcome;
}
