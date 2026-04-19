"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Menu, X } from "lucide-react";
import { ConnectForm } from "@/components/connect-form";
import { Sidebar } from "@/components/sidebar";
import { ChatView } from "@/components/chat-view";
import { createSession, deleteSession, listSessions } from "@/lib/api";
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
  const refreshRequestIdRef = useRef(0);

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
  const refreshSessions = useCallback(async (srv: string, tok: string) => {
    if (!srv || !tok) return;

    const requestId = ++refreshRequestIdRef.current;
    setRefreshingSessions(true);

    try {
      const list = await listSessions(srv, tok);

      if (requestId !== refreshRequestIdRef.current) return;

      setSessions(list);
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
      void refreshSessions(server, token);
    }, 0);

    return () => {
      clearTimeout(timer);
    };
  }, [connected, refreshSessions, server, token]);

  function handleConnect(srv: string, tok: string) {
    saveConnection(srv, tok);
    setConnection({ connected: true, server: srv, token: tok });
  }

  function handleDisconnect() {
    refreshRequestIdRef.current += 1;
    clearConnection();
    setRefreshingSessions(false);
    setConnection({ connected: false, server: "", token: "" });
    setSessions([]);
    setActiveSessionId(null);
  }

  async function handleNewSession() {
    setCreatingSession(true);
    try {
      const session = await createSession(server, token);
      setSessions((prev) => [session, ...prev]);
      setActiveSessionId(session.session_id);
      setSidebarOpen(false);
    } catch {
      // handled in UI
    } finally {
      setCreatingSession(false);
    }
  }

  async function handleDeleteSession(id: string) {
    try {
      await deleteSession(server, token, id);
      setSessions((prev) => prev.filter((s) => s.session_id !== id));
      if (activeSessionId === id) setActiveSessionId(null);
    } catch {
      // deletion failed silently
    }
  }

  function handleSelectSession(id: string) {
    setActiveSessionId(id);
    setSidebarOpen(false);
  }

  function handleTitleUpdate(sessionId: string, title: string) {
    setSessions((prev) =>
      prev.map((s) => (s.session_id === sessionId ? { ...s, title } : s)),
    );
  }

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
          onDelete={handleDeleteSession}
          onDisconnect={handleDisconnect}
          loading={loading}
        />
      </aside>

      {/* Main content */}
      <main className="flex flex-1 flex-col min-w-0">
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
          <span className="text-sm font-semibold">Carapace</span>
        </div>

        {/* Chat or empty state */}
        {activeSessionId ? (
          <ChatView
            key={activeSessionId}
            server={server}
            token={token}
            sessionId={activeSessionId}
            onTitleUpdate={(title) => handleTitleUpdate(activeSessionId, title)}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center">
            <div className="text-center">
              <p className="text-lg font-medium text-foreground/80">Carapace</p>
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
