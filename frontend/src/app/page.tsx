"use client";

import { useCallback, useEffect, useState } from "react";
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

export default function Home() {
  const [connected, setConnected] = useState(false);
  const [server, setServer] = useState("");
  const [token, setToken] = useState("");
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  // Restore connection on mount
  useEffect(() => {
    if (hasConnection()) {
      setServer(getServer());
      setToken(getToken());
      setConnected(true);
    }
  }, []);

  // Fetch sessions when connected
  const refreshSessions = useCallback(async () => {
    if (!server || !token) return;
    setLoading(true);
    try {
      const list = await listSessions(server, token);
      setSessions(list);
    } catch {
      // If sessions fail to load, connection might be stale
    } finally {
      setLoading(false);
    }
  }, [server, token]);

  useEffect(() => {
    if (connected) refreshSessions();
  }, [connected, refreshSessions]);

  function handleConnect(srv: string, tok: string) {
    saveConnection(srv, tok);
    setServer(srv);
    setToken(tok);
    setConnected(true);
  }

  function handleDisconnect() {
    clearConnection();
    setConnected(false);
    setServer("");
    setToken("");
    setSessions([]);
    setActiveSessionId(null);
  }

  async function handleNewSession() {
    setLoading(true);
    try {
      const session = await createSession(server, token);
      setSessions((prev) => [session, ...prev]);
      setActiveSessionId(session.session_id);
      setSidebarOpen(false);
    } catch {
      // handled in UI
    } finally {
      setLoading(false);
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
          "fixed inset-y-0 left-0 z-40 w-72 border-r border-border bg-background transition-transform duration-200 md:static md:translate-x-0",
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
            className="rounded-md p-1.5 hover:bg-muted transition-colors"
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
