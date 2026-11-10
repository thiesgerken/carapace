"use client";

import { useEffect, useState } from "react";
import { searchSessions } from "@/lib/api";
import type { SessionSearchHit } from "@/lib/types";

const SEARCH_DEBOUNCE_MS = 250;

export type SessionSearchMode = "title" | "fulltext";

export interface SessionSearchResult {
  /** `null` while the query is blank, so the caller shows its normal list instead. */
  hits: SessionSearchHit[] | null;
  loading: boolean;
  failed: boolean;
}

/**
 * Debounced session search. A new `refreshKey` re-runs the current query, e.g. after a row action
 * changed or deleted a hit.
 */
export function useSessionSearch(
  server: string,
  token: string,
  query: string,
  mode: SessionSearchMode,
  refreshKey: number,
): SessionSearchResult {
  const trimmed = query.trim();
  const requestKey = JSON.stringify([trimmed, mode, refreshKey]);
  // Hits stay keyed by the request that produced them, so the previous hits stay visible while the
  // next query loads instead of the list flashing empty on every keystroke.
  const [settled, setSettled] = useState<{ requestKey: string; hits: SessionSearchHit[]; failed: boolean } | null>(null);

  useEffect(() => {
    if (!trimmed || !server || !token) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      searchSessions(server, token, trimmed, { fulltext: mode === "fulltext" })
        .then((hits) => {
          if (!cancelled) setSettled({ requestKey, hits, failed: false });
        })
        .catch(() => {
          if (!cancelled) setSettled({ requestKey, hits: [], failed: true });
        });
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [mode, requestKey, server, token, trimmed]);

  if (!trimmed) return { hits: null, loading: false, failed: false };
  const current = settled?.requestKey === requestKey;
  return {
    hits: settled?.hits ?? [],
    loading: !current,
    failed: current && settled?.failed === true,
  };
}
