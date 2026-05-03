"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Menu, X } from "lucide-react";
import { ConnectForm } from "@/components/connect-form";
import { Sidebar } from "@/components/sidebar";
import { ChatView } from "@/components/chat-view";
import { createSession, deleteSession, getSession, listSessionsPage, updateSession } from "@/lib/api";
import {
  clearConnection,
  getServer,
  getToken,
  hasConnection,
  saveConnection,
} from "@/lib/storage";
import type { SessionInfo } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useSwipeDrawer } from "@/hooks/use-swipe-drawer";

function sandboxTimestampValue(sandbox: SessionInfo["sandbox"] | null | undefined): number {
  const updatedAt = sandbox?.updated_at;
  if (!updatedAt) return 0;
  const value = Date.parse(updatedAt);
  return Number.isNaN(value) ? 0 : value;
}

const SESSION_PAGE_SIZE = 50;

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

type ConnectionState = {
  connected: boolean;
  server: string;
  token: string;
};

function loadStoredConnection(): ConnectionState {
  if (!hasConnection()) {
    return {
      connected: false,
      server: "",
      token: "",
    };
  }

  return {
    connected: true,
    server: getServer(),
    token: getToken(),
  };
}

export default function Home() {
  return (
    <Suspense>
      <HomeContent />
    </Suspense>
  );
}

function HomeContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [connection, setConnection] = useState<ConnectionState>({
    connected: false,
    server: "",
    token: "",
  });
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(
    searchParams.get("session"),
  );
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [creatingSession, setCreatingSession] = useState(false);
  const [refreshingSessions, setRefreshingSessions] = useState(false);
  const [loadingMoreSessions, setLoadingMoreSessions] = useState(false);
  const [sessionListCursor, setSessionListCursor] = useState<string | null>(null);
  const [sessionListHasMore, setSessionListHasMore] = useState(false);
  const refreshRequestIdRef = useRef(0);
  const loadingMoreSessionsRef = useRef(false);
  const pendingSandboxUpdatesRef = useRef(new Map<string, SessionInfo["sandbox"]>());

  const { connected, server, token } = connection;
  const loading = creatingSession || refreshingSessions;

  useSwipeDrawer(sidebarOpen, setSidebarOpen);

  // Sync activeSessionId → URL query param
  useEffect(() => {
    if (activeSessionId) {
      router.replace(`?session=${encodeURIComponent(activeSessionId)}`, {
        scroll: false,
      });
    } else {
      router.replace("/", { scroll: false });
    }
  }, [activeSessionId, router]);

  useEffect(() => {
    // Defer to avoid synchronous setState in effect body.
    const timer = setTimeout(() => {
      const nextConnection = loadStoredConnection();
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
    }, 0);

    return () => {
      clearTimeout(timer);
    };
  }, []);

  // Fetch sessions when connected
  const loadInitialSessions = useCallback(async (srv: string, tok: string) => {
    if (!srv || !tok) return;

    const requestId = ++refreshRequestIdRef.current;
    setRefreshingSessions(true);
    loadingMoreSessionsRef.current = false;
    setLoadingMoreSessions(false);

    try {
      const page = await listSessionsPage(srv, tok, {
        includeArchived: true,
        includeMessageCount: true,
        limit: SESSION_PAGE_SIZE,
      });

      if (requestId !== refreshRequestIdRef.current) return;

      setSessions((current) => mergeSessions(current, page.items, pendingSandboxUpdatesRef.current));
      setSessionListCursor(page.next_cursor ?? null);
      setSessionListHasMore(page.has_more);
    } catch {
      // If sessions fail to load, connection might be stale
    } finally {
      if (requestId === refreshRequestIdRef.current) {
        setRefreshingSessions(false);
      }
    }
  }, []);

  useEffect(() => {
    if (!connected) return;

    // Defer to avoid synchronous setState in effect body.
    const timer = setTimeout(() => {
      void loadInitialSessions(server, token);
    }, 0);

    return () => {
      clearTimeout(timer);
    };
  }, [connected, loadInitialSessions, server, token]);

  const loadMoreSessions = useCallback(async () => {
    if (!server || !token || refreshingSessions || loadingMoreSessionsRef.current || !sessionListHasMore || !sessionListCursor) {
      return;
    }

    const requestId = refreshRequestIdRef.current;
    loadingMoreSessionsRef.current = true;
    setLoadingMoreSessions(true);

    try {
      const page = await listSessionsPage(server, token, {
        includeArchived: true,
        includeMessageCount: true,
        limit: SESSION_PAGE_SIZE,
        cursor: sessionListCursor,
      });

      if (requestId !== refreshRequestIdRef.current) return;

      setSessions((current) => mergeSessions(current, page.items, pendingSandboxUpdatesRef.current));
      setSessionListCursor(page.next_cursor ?? null);
      setSessionListHasMore(page.has_more);
    } catch {
      // Ignore transient pagination failures and allow a later retry.
    } finally {
      if (requestId === refreshRequestIdRef.current) {
        loadingMoreSessionsRef.current = false;
        setLoadingMoreSessions(false);
      }
    }
  }, [refreshingSessions, server, sessionListCursor, sessionListHasMore, token]);

  useEffect(() => {
    if (!connected || !activeSessionId) return;
    if (sessions.some((session) => session.session_id === activeSessionId)) return;

    let cancelled = false;
    const requestId = refreshRequestIdRef.current;
    const timer = setTimeout(() => {
      void getSession(server, token, activeSessionId)
        .then((session) => {
          if (cancelled || requestId !== refreshRequestIdRef.current) return;
          setSessions((current) => mergeSessions(current, [session], pendingSandboxUpdatesRef.current));
        })
        .catch(() => {
          // Leave the active id alone; ChatView will surface session-specific failures if needed.
        });
    }, 0);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [activeSessionId, connected, server, sessions, token]);

  function handleConnect(srv: string, tok: string) {
    refreshRequestIdRef.current += 1;
    loadingMoreSessionsRef.current = false;
    pendingSandboxUpdatesRef.current.clear();
    setRefreshingSessions(false);
    setLoadingMoreSessions(false);
    setSessions([]);
    setSessionListCursor(null);
    setSessionListHasMore(false);
    saveConnection(srv, tok);
    setConnection({ connected: true, server: srv, token: tok });
  }

  function handleDisconnect() {
    refreshRequestIdRef.current += 1;
    loadingMoreSessionsRef.current = false;
    pendingSandboxUpdatesRef.current.clear();
    clearConnection();
    setRefreshingSessions(false);
    setLoadingMoreSessions(false);
    setConnection({ connected: false, server: "", token: "" });
    setSessions([]);
    setSessionListCursor(null);
    setSessionListHasMore(false);
    setActiveSessionId(null);
  }

  async function handleNewSession() {
    setCreatingSession(true);
    try {
      const session = await createSession(server, token);
      setSessions((prev) => sortSessions([session, ...prev]));
      setActiveSessionId(session.session_id);
      setSidebarOpen(false);
    } catch {
      // handled in UI
    } finally {
      setCreatingSession(false);
    }
  }

  const handleDeleteSession = useCallback(async (id: string) => {
    try {
      await deleteSession(server, token, id);
      pendingSandboxUpdatesRef.current.delete(id);
      setSessions((prev) => prev.filter((s) => s.session_id !== id));
      setActiveSessionId((current) => (current === id ? null : current));
    } catch {
      // deletion failed silently
    }
  }, [server, token]);

  const handleUpdateSessionAttributes = useCallback(async (
    id: string,
    attributes: NonNullable<Parameters<typeof updateSession>[3]["attributes"]>,
  ) => {
    const updated = await updateSession(server, token, id, { attributes });
    pendingSandboxUpdatesRef.current.delete(id);
    setSessions((prev) => sortSessions(prev.map((entry) => (entry.session_id === id ? { ...entry, ...updated } : entry))));
    setActiveSessionId((current) => (updated.attributes.archived && current === id ? null : current));
    return updated;
  }, [server, token]);

  function handleSelectSession(id: string) {
    setActiveSessionId(id);
    setSidebarOpen(false);
  }

  function handleTitleUpdate(sessionId: string, title: string) {
    setSessions((prev) =>
      prev.map((s) => (s.session_id === sessionId ? { ...s, title } : s)),
    );
  }

  function handleSessionUpdate(session: SessionInfo) {
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
  }

  function handleSandboxUpdate(sessionId: string, sandbox: SessionInfo["sandbox"]) {
    pendingSandboxUpdatesRef.current.set(sessionId, sandbox);
    setSessions((prev) =>
      prev.map((s) => (s.session_id === sessionId ? { ...s, sandbox } : s)),
    );
  }

  const handleActiveSessionTitleUpdate = useCallback((title: string) => {
    if (!activeSessionId) return;
    handleTitleUpdate(activeSessionId, title);
  }, [activeSessionId]);

  const handleActiveSessionSandboxUpdate = useCallback((sandbox: SessionInfo["sandbox"]) => {
    if (!activeSessionId) return;
    handleSandboxUpdate(activeSessionId, sandbox);
  }, [activeSessionId]);

  const handleActiveSessionUpdate = useCallback((session: SessionInfo) => {
    handleSessionUpdate(session);
  }, []);

  const handleForkSession = useCallback((session: SessionInfo) => {
    handleSessionUpdate(session);
    setActiveSessionId(session.session_id);
    setSidebarOpen(false);
  }, []);

  const handleActiveSessionDelete = useCallback(async () => {
    if (!activeSessionId) return;
    await handleDeleteSession(activeSessionId);
  }, [activeSessionId, handleDeleteSession]);

  const activeSession = sessions.find((session) => session.session_id === activeSessionId) ?? null;

  if (!connected) {
    return <ConnectForm onConnect={handleConnect} />;
  }

  return (
    <div className="flex h-dvh overflow-hidden">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 w-72 border-r border-border bg-background transition-transform duration-200 md:static md:w-80 md:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <Sidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelect={handleSelectSession}
          onNew={handleNewSession}
          onUpdateAttributes={handleUpdateSessionAttributes}
          onDelete={handleDeleteSession}
          onDisconnect={handleDisconnect}
          loading={loading}
          hasMore={sessionListHasMore}
          loadingMore={loadingMoreSessions}
          onLoadMore={loadMoreSessions}
        />
      </aside>

      {/* Main content */}
      <main className="flex min-h-0 flex-1 flex-col min-w-0 overflow-hidden">
        {/* Mobile header */}
        <div className="flex items-center gap-3 border-b border-border px-4 py-2 md:hidden">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="rounded-md p-2.5 hover:bg-muted transition-colors"
          >
            {sidebarOpen ? (
              <X className="h-5 w-5" />
            ) : (
              <Menu className="h-5 w-5" />
            )}
          </button>
          <span className="text-sm font-semibold">carapace</span>
        </div>

        {/* Chat or empty state */}
        {activeSessionId ? (
          <ChatView
            key={activeSessionId}
            server={server}
            token={token}
            sessionId={activeSessionId}
            session={activeSession}
            initialSandbox={activeSession?.sandbox ?? null}
            onTitleUpdate={handleActiveSessionTitleUpdate}
            onSessionUpdate={handleActiveSessionUpdate}
            onSandboxUpdate={handleActiveSessionSandboxUpdate}
            onForkSession={handleForkSession}
            onUpdateSessionAttributes={handleUpdateSessionAttributes}
            onDeleteSession={handleActiveSessionDelete}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center">
            <div className="text-center">
              <p className="text-lg font-medium text-foreground/80">carapace</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Select a session or start a new one
              </p>
              <button
                onClick={handleNewSession}
                disabled={loading}
                className={cn(
                  "mt-4 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
                  "bg-foreground text-background hover:bg-foreground/90",
                  "disabled:opacity-50",
                )}
              >
                New session
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
