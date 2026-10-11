"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  AUTH_REQUIRED_EVENT,
  createSession,
  deleteSession,
  getCurrentUser,
  getSandboxGit,
  getServerMeta,
  getSession,
  listSessions,
  logout,
  updateSession,
  type AuthUserInfo,
} from "@/lib/api";
import { type NewSessionOptions } from "@/components/new-session-button";
import {
  clearChatDraft,
  clearConnection,
  getServer,
  getShowArchivedSessionsPreference,
  getToken,
  hasConnection,
  saveConnection,
  saveShowArchivedSessionsPreference,
} from "@/lib/storage";
import type { SessionInfo } from "@/lib/types";
import { useTranslations } from "next-intl";

const SESSION_PAGE_SIZE = 50;

function sandboxTimestampValue(sandbox: SessionInfo["sandbox"] | null | undefined): number {
  const updatedAt = sandbox?.updated_at;
  if (!updatedAt) return 0;
  const value = Date.parse(updatedAt);
  return Number.isNaN(value) ? 0 : value;
}

function mergeSessions(
  current: SessionInfo[],
  incoming: SessionInfo[],
  pending: Map<string, SessionInfo["sandbox"]>,
): SessionInfo[] {
  const merged = new Map(current.map((session) => [session.session_id, session]));
  for (const session of incoming) {
    const existing = merged.get(session.session_id);
    const pendingSandbox = pending.get(session.session_id);
    const freshestSandbox = [session.sandbox, existing?.sandbox, pendingSandbox].reduce<SessionInfo["sandbox"]>(
      (freshest, candidate) =>
        sandboxTimestampValue(candidate) > sandboxTimestampValue(freshest) ? candidate : freshest,
      session.sandbox,
    );
    const mergedSession = existing ? { ...existing, ...session } : session;
    merged.set(
      session.session_id,
      freshestSandbox === mergedSession.sandbox
        ? mergedSession
        : { ...mergedSession, sandbox: freshestSandbox },
    );
  }
  return sortSessions([...merged.values()]);
}

function compareSessions(left: SessionInfo, right: SessionInfo): number {
  if (left.attributes.pinned !== right.attributes.pinned) {
    return left.attributes.pinned ? -1 : 1;
  }

  const leftTime = Date.parse(left.last_active);
  const rightTime = Date.parse(right.last_active);
  const normalizedLeft = Number.isNaN(leftTime) ? 0 : leftTime;
  const normalizedRight = Number.isNaN(rightTime) ? 0 : rightTime;
  if (normalizedLeft !== normalizedRight) {
    return normalizedRight - normalizedLeft;
  }

  return left.session_id.localeCompare(right.session_id);
}

function sortSessions(sessions: SessionInfo[]): SessionInfo[] {
  return [...sessions].sort(compareSessions);
}

export interface AppShell {
  connected: boolean;
  server: string;
  token: string;
  currentUser: AuthUserInfo | null;
  onRefreshCurrentUser: () => void;
  isAdmin: boolean;
  serverVersion: string | null;
  sessions: SessionInfo[];
  activeSessionId: string | null;
  activeSession: SessionInfo | null;
  showArchivedSessions: boolean;
  loading: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  onConnect: (user: AuthUserInfo) => void;
  onDisconnect: () => void;
  onSelectSession: (id: string) => void;
  /** Resolves to the created session, or null when creating it failed. */
  onNewSession: (options?: NewSessionOptions) => Promise<SessionInfo | null>;
  onGoHome: () => void;
  onOpenSettings: (tab?: string) => void;
  onOpenJobSettings: (jobId: string) => void;
  onShowArchivedSessionsChange: (showArchivedSessions: boolean) => void;
  onUpdateSessionAttributes: (
    id: string,
    attributes: NonNullable<Parameters<typeof updateSession>[3]["attributes"]>,
  ) => Promise<SessionInfo>;
  onDeleteSession: (id: string, options?: { skipUnpushedWarning?: boolean }) => Promise<void>;
  onForkSession: (session: SessionInfo) => void;
  onLoadMore: () => void;
  onSessionUpdate: (session: SessionInfo) => void;
  onTitleUpdate: (sessionId: string, title: string) => void;
  onSandboxUpdate: (sessionId: string, sandbox: SessionInfo["sandbox"]) => void;
}

const AppShellContext = createContext<AppShell | null>(null);

export function useAppShell(): AppShell {
  const value = useContext(AppShellContext);
  if (!value) {
    throw new Error("useAppShell must be used within an AppShellProvider");
  }
  return value;
}

type ConnectionState = {
  connected: boolean;
  server: string;
  token: string;
};

function loadStoredConnection(): ConnectionState {
  if (!hasConnection()) {
    return { connected: false, server: "", token: "" };
  }
  return { connected: true, server: getServer(), token: getToken() };
}

export function AppShellProvider({ children }: { children: ReactNode }) {
  const t = useTranslations();
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeSessionId = searchParams.get("session");

  const [connection, setConnection] = useState<ConnectionState>({ connected: false, server: "", token: "" });
  const [currentUser, setCurrentUser] = useState<AuthUserInfo | null>(null);
  const [serverVersion, setServerVersion] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [showArchivedSessions, setShowArchivedSessionsState] = useState(false);
  const [refreshingSessions, setRefreshingSessions] = useState(false);
  const [loadingMoreSessions, setLoadingMoreSessions] = useState(false);
  const [creatingSession, setCreatingSession] = useState(false);
  const [sessionListInitialized, setSessionListInitialized] = useState(false);
  const [sessionListCursor, setSessionListCursor] = useState<string | null>(null);
  const [sessionListHasMore, setSessionListHasMore] = useState(false);
  const refreshRequestIdRef = useRef(0);
  const loadingMoreSessionsRef = useRef(false);
  const failedLoadMoreCursorRef = useRef<string | null>(null);
  const pendingSandboxUpdatesRef = useRef(new Map<string, SessionInfo["sandbox"]>());

  const { connected, server, token } = connection;
  const isAdmin = currentUser?.roles.includes("admin") ?? false;
  const loading = creatingSession || refreshingSessions;
  const hasActiveSessionLoaded = activeSessionId != null
    && sessions.some((session) => session.session_id === activeSessionId);
  const activeSession = sessions.find((session) => session.session_id === activeSessionId) ?? null;

  useEffect(() => {
    // Defer to avoid synchronous setState in effect body.
    const timer = setTimeout(() => {
      const nextConnection = loadStoredConnection();
      const nextShowArchivedSessions = getShowArchivedSessionsPreference();
      setConnection((current) => {
        if (
          current.connected === nextConnection.connected
          && current.server === nextConnection.server
          && current.token === nextConnection.token
        ) {
          return current;
        }
        return nextConnection;
      });
      setShowArchivedSessionsState((current) =>
        current === nextShowArchivedSessions ? current : nextShowArchivedSessions,
      );
    }, 0);

    return () => {
      clearTimeout(timer);
    };
  }, []);

  const loadInitialSessions = useCallback(async (
    srv: string,
    tok: string,
    includeArchived: boolean,
  ) => {
    if (!srv || !tok) return;

    const requestId = ++refreshRequestIdRef.current;
    setRefreshingSessions(true);
    setSessionListInitialized(false);
    loadingMoreSessionsRef.current = false;
    failedLoadMoreCursorRef.current = null;
    setLoadingMoreSessions(false);

    try {
      const page = await listSessions(srv, tok, {
        includeArchived,
        includeMessageCount: true,
        limit: SESSION_PAGE_SIZE,
      });

      if (requestId !== refreshRequestIdRef.current) return;

      setSessions(mergeSessions([], page.items, pendingSandboxUpdatesRef.current));
      setSessionListCursor(page.next_cursor ?? null);
      setSessionListHasMore(page.has_more);
      failedLoadMoreCursorRef.current = null;
    } catch {
      // If sessions fail to load, connection might be stale
    } finally {
      if (requestId === refreshRequestIdRef.current) {
        setRefreshingSessions(false);
        setSessionListInitialized(true);
      }
    }
  }, []);

  useEffect(() => {
    if (!connected) return;

    const timer = setTimeout(() => {
      void loadInitialSessions(server, token, showArchivedSessions);
    }, 0);

    return () => {
      clearTimeout(timer);
    };
  }, [connected, loadInitialSessions, server, showArchivedSessions, token]);

  // Settings that change the user's own config (agent name, icon) have to land in the
  // shell too, or the sidebar and favicon keep rendering the pre-save values.
  const onRefreshCurrentUser = useCallback(() => {
    if (!connected || !server) {
      setCurrentUser(null);
      return;
    }
    void getCurrentUser(server)
      .then(setCurrentUser)
      .catch(() => setCurrentUser(null));
  }, [connected, server]);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      if (!connected || !server) {
        if (!cancelled) setCurrentUser(null);
        return;
      }

      void getCurrentUser(server)
        .then((user) => {
          if (!cancelled) setCurrentUser(user);
        })
        .catch(() => {
          if (!cancelled) setCurrentUser(null);
        });
    }, 0);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [connected, server, token]);

  const requireLogin = useCallback(() => {
    refreshRequestIdRef.current += 1;
    loadingMoreSessionsRef.current = false;
    failedLoadMoreCursorRef.current = null;
    pendingSandboxUpdatesRef.current.clear();
    setCurrentUser(null);
    setRefreshingSessions(false);
    setLoadingMoreSessions(false);
    setSessionListInitialized(false);
    setConnection({ connected: false, server: "", token: "" });
    setServerVersion(null);
    setSessions([]);
    setSessionListCursor(null);
    setSessionListHasMore(false);
    router.replace("/");
  }, [router]);

  useEffect(() => {
    window.addEventListener(AUTH_REQUIRED_EVENT, requireLogin);
    return () => {
      window.removeEventListener(AUTH_REQUIRED_EVENT, requireLogin);
    };
  }, [requireLogin]);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      if (!connected || !server || !token) {
        if (!cancelled) {
          setServerVersion(null);
        }
        return;
      }

      void getServerMeta(server, token)
        .then((meta) => {
          if (!cancelled) {
            setServerVersion(meta.version);
          }
        })
        .catch(() => {
          if (!cancelled) {
            setServerVersion(null);
          }
        });
    }, 0);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [connected, server, token]);

  const onLoadMore = useCallback(async () => {
    if (
      !server
      || !token
      || refreshingSessions
      || loadingMoreSessionsRef.current
      || !sessionListHasMore
      || !sessionListCursor
      || failedLoadMoreCursorRef.current === sessionListCursor
    ) {
      return;
    }

    const requestId = refreshRequestIdRef.current;
    loadingMoreSessionsRef.current = true;
    setLoadingMoreSessions(true);

    try {
      const page = await listSessions(server, token, {
        includeArchived: showArchivedSessions,
        includeMessageCount: true,
        limit: SESSION_PAGE_SIZE,
        cursor: sessionListCursor,
      });

      if (requestId !== refreshRequestIdRef.current) return;

      setSessions((current) => mergeSessions(current, page.items, pendingSandboxUpdatesRef.current));
      setSessionListCursor(page.next_cursor ?? null);
      setSessionListHasMore(page.has_more);
      failedLoadMoreCursorRef.current = null;
    } catch {
      failedLoadMoreCursorRef.current = sessionListCursor;
    } finally {
      if (requestId === refreshRequestIdRef.current) {
        loadingMoreSessionsRef.current = false;
        setLoadingMoreSessions(false);
      }
    }
  }, [refreshingSessions, server, sessionListCursor, sessionListHasMore, showArchivedSessions, token]);

  const onShowArchivedSessionsChange = useCallback((nextShowArchivedSessions: boolean) => {
    saveShowArchivedSessionsPreference(nextShowArchivedSessions);
    setShowArchivedSessionsState(nextShowArchivedSessions);
  }, []);

  // Hydrate an active session that isn't in the loaded page yet (deep link).
  useEffect(() => {
    if (!connected || !activeSessionId || !sessionListInitialized || hasActiveSessionLoaded) return;

    let cancelled = false;
    const requestId = refreshRequestIdRef.current;
    const timer = setTimeout(() => {
      void getSession(server, token, activeSessionId)
        .then((session) => {
          if (cancelled || requestId !== refreshRequestIdRef.current) return;
          setSessions((current) => mergeSessions(current, [session], pendingSandboxUpdatesRef.current));
        })
        .catch(() => {
          // Leave the active id alone; ChatView surfaces session-specific failures if needed.
        });
    }, 0);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [activeSessionId, connected, hasActiveSessionLoaded, server, sessionListInitialized, token]);

  const onConnect = useCallback((user: AuthUserInfo) => {
    const srv = getServer();
    refreshRequestIdRef.current += 1;
    loadingMoreSessionsRef.current = false;
    failedLoadMoreCursorRef.current = null;
    pendingSandboxUpdatesRef.current.clear();
    setRefreshingSessions(false);
    setLoadingMoreSessions(false);
    setSessionListInitialized(false);
    setSessions([]);
    setSessionListCursor(null);
    setSessionListHasMore(false);
    saveConnection(user.username);
    setCurrentUser(user);
    setConnection({ connected: true, server: srv, token: user.username });
  }, []);

  const onDisconnect = useCallback(() => {
    if (server) {
      void logout(server).catch(() => undefined);
    }
    clearConnection();
    requireLogin();
  }, [requireLogin, server]);

  const onNewSession = useCallback(async (options: NewSessionOptions = {}) => {
    setCreatingSession(true);
    try {
      const session = await createSession(server, token, options);
      setSessions((prev) => sortSessions([session, ...prev]));
      router.push(`/?session=${session.session_id}`);
      return session;
    } catch {
      // handled in UI
      return null;
    } finally {
      setCreatingSession(false);
    }
  }, [router, server, token]);

  const onDeleteSession = useCallback(async (id: string, options?: { skipUnpushedWarning?: boolean }) => {
    // Warn about unpushed sandbox commits. The backend status check never boots
    // a stopped sandbox (returns running=false / no counts), so we ask it
    // directly rather than trusting the possibly-stale cached row snapshot.
    // Shift+click (skipUnpushedWarning) skips this, matching the confirm skip.
    if (!options?.skipUnpushedWarning) {
      try {
        const git = await getSandboxGit(server, token, id, { fetch: false });
        const ahead = git.running && git.upstream ? (git.ahead ?? 0) : 0;
        if (ahead > 0 && !window.confirm(t("sidebar.confirm.deleteUnpushed", { count: ahead }))) {
          return;
        }
      } catch {
        // status check failed — fall through and delete
      }
    }
    try {
      await deleteSession(server, token, id);
      clearChatDraft(id);
      pendingSandboxUpdatesRef.current.delete(id);
      setSessions((prev) => prev.filter((s) => s.session_id !== id));
      if (activeSessionId === id) {
        router.push("/");
      }
    } catch {
      // deletion failed silently
    }
  }, [activeSessionId, router, server, t, token]);

  const onUpdateSessionAttributes = useCallback(async (
    id: string,
    attributes: NonNullable<Parameters<typeof updateSession>[3]["attributes"]>,
  ) => {
    const updated = await updateSession(server, token, id, { attributes });
    pendingSandboxUpdatesRef.current.delete(id);
    setSessions((prev) => sortSessions(prev.map((entry) => (entry.session_id === id ? { ...entry, ...updated } : entry))));
    if (updated.attributes.archived && activeSessionId === id) {
      router.push("/");
    }
    return updated;
  }, [activeSessionId, router, server, token]);

  const onSessionUpdate = useCallback((session: SessionInfo) => {
    setSessions((prev) => {
      const next = prev.map((entry) =>
        entry.session_id === session.session_id ? { ...entry, ...session } : entry,
      );
      return sortSessions(
        next.some((entry) => entry.session_id === session.session_id)
          ? next
          : [session, ...next],
      );
    });
  }, []);

  const onTitleUpdate = useCallback((sessionId: string, title: string) => {
    setSessions((prev) =>
      prev.map((s) => (s.session_id === sessionId ? { ...s, title } : s)),
    );
  }, []);

  const onSandboxUpdate = useCallback((sessionId: string, sandbox: SessionInfo["sandbox"]) => {
    pendingSandboxUpdatesRef.current.set(sessionId, sandbox);
    setSessions((prev) =>
      prev.map((s) => (s.session_id === sessionId ? { ...s, sandbox } : s)),
    );
  }, []);

  const onForkSession = useCallback((session: SessionInfo) => {
    onSessionUpdate(session);
    router.push(`/?session=${session.session_id}`);
  }, [onSessionUpdate, router]);

  const onSelectSession = useCallback((id: string) => {
    router.push(`/?session=${id}`);
  }, [router]);

  const onGoHome = useCallback(() => {
    router.push("/");
  }, [router]);

  const onOpenSettings = useCallback((tab: string = "preferences") => {
    router.push(`/settings/${tab}`);
  }, [router]);

  const onOpenJobSettings = useCallback((jobId: string) => {
    router.push(`/settings/jobs?job=${encodeURIComponent(jobId)}`);
  }, [router]);

  const value = useMemo<AppShell>(() => ({
    connected,
    server,
    token,
    currentUser,
    onRefreshCurrentUser,
    isAdmin,
    serverVersion,
    sessions,
    activeSessionId,
    activeSession,
    showArchivedSessions,
    loading,
    hasMore: sessionListHasMore,
    loadingMore: loadingMoreSessions,
    onConnect,
    onDisconnect,
    onSelectSession,
    onNewSession,
    onGoHome,
    onOpenSettings,
    onOpenJobSettings,
    onShowArchivedSessionsChange,
    onUpdateSessionAttributes,
    onDeleteSession,
    onForkSession,
    onLoadMore,
    onSessionUpdate,
    onTitleUpdate,
    onSandboxUpdate,
  }), [
    activeSession,
    activeSessionId,
    connected,
    currentUser,
    onRefreshCurrentUser,
    isAdmin,
    loading,
    loadingMoreSessions,
    onConnect,
    onDeleteSession,
    onDisconnect,
    onForkSession,
    onGoHome,
    onLoadMore,
    onNewSession,
    onOpenJobSettings,
    onOpenSettings,
    onSandboxUpdate,
    onSelectSession,
    onSessionUpdate,
    onShowArchivedSessionsChange,
    onTitleUpdate,
    onUpdateSessionAttributes,
    server,
    serverVersion,
    sessions,
    sessionListHasMore,
    showArchivedSessions,
    token,
  ]);

  return <AppShellContext.Provider value={value}>{children}</AppShellContext.Provider>;
}
