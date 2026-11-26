import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/** How long an archive waits for an undo before it reaches the server. */
export const ARCHIVE_UNDO_DELAY_MS = 5_000;

type PendingArchive = {
  sessionId: string;
  timeout: ReturnType<typeof setTimeout>;
  settle: () => void;
};

export type DelayedArchive = {
  /** The session whose archive is waiting for an undo, if any. */
  pendingSessionId: string | null;
  /** Sessions to show as archived already: the waiting one and those whose request is still running. */
  archivingSessionIds: readonly string[];
  /** Archives after the delay; settles once the archive request finished or was undone. */
  schedule: (sessionId: string) => Promise<void>;
  /** Drops the waiting archive, so the server never hears of it. */
  undo: () => void;
  /** Sends the waiting archive right away. */
  commitNow: () => void;
};

/**
 * Archiving commits a session to knowledge and tears down its sandbox, which the server can't take back. So the
 * request waits a few seconds and an undo in that window means it never happened. One archive waits at a time:
 * scheduling another sends the waiting one first. Closing the page in the window drops it, on purpose.
 */
export function useDelayedArchive(archive: (sessionId: string) => Promise<unknown>): DelayedArchive {
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(null);
  const [sendingSessionIds, setSendingSessionIds] = useState<readonly string[]>([]);
  const pendingRef = useRef<PendingArchive | null>(null);
  const archiveRef = useRef(archive);

  useEffect(() => {
    archiveRef.current = archive;
  }, [archive]);

  const takePending = useCallback((): PendingArchive | null => {
    const pending = pendingRef.current;
    if (!pending) return null;
    clearTimeout(pending.timeout);
    pendingRef.current = null;
    setPendingSessionId(null);
    return pending;
  }, []);

  const commitNow = useCallback(() => {
    const pending = takePending();
    if (!pending) return;
    const { sessionId } = pending;
    setSendingSessionIds((ids) => [...ids, sessionId]);
    archiveRef.current(sessionId)
      .catch((error: unknown) => console.error(`Failed to archive session ${sessionId}`, error))
      .finally(() => {
        setSendingSessionIds((ids) => ids.filter((id) => id !== sessionId));
        pending.settle();
      });
  }, [takePending]);

  const undo = useCallback(() => {
    takePending()?.settle();
  }, [takePending]);

  const schedule = useCallback((sessionId: string) => {
    commitNow();
    return new Promise<void>((resolve) => {
      pendingRef.current = { sessionId, settle: resolve, timeout: setTimeout(commitNow, ARCHIVE_UNDO_DELAY_MS) };
      setPendingSessionId(sessionId);
    });
  }, [commitNow]);

  useEffect(() => () => {
    const pending = pendingRef.current;
    if (pending) clearTimeout(pending.timeout);
  }, []);

  const archivingSessionIds = useMemo(
    () => (pendingSessionId ? [pendingSessionId, ...sendingSessionIds] : sendingSessionIds),
    [pendingSessionId, sendingSessionIds],
  );

  return { pendingSessionId, archivingSessionIds, schedule, undo, commitNow };
}
