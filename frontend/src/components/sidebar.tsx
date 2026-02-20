"use client";

import { Plus, LogOut, MessageSquare, Trash2 } from "lucide-react";
import type { SessionInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SidebarProps {
  sessions: SessionInfo[];
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onNew: () => void;
  onDelete: (sessionId: string) => void;
  onDisconnect: () => void;
  loading?: boolean;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return d.toLocaleDateString();
}

export function Sidebar({
  sessions,
  activeSessionId,
  onSelect,
  onNew,
  onDelete,
  onDisconnect,
  loading,
}: SidebarProps) {
  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <span className="text-sm font-semibold tracking-tight">Carapace</span>
        <button
          onClick={onDisconnect}
          title="Disconnect"
          className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>

      {/* New session button */}
      <div className="px-3 pt-3 pb-1">
        <button
          onClick={onNew}
          disabled={loading}
          className={cn(
            "flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm",
            "hover:bg-muted transition-colors",
            "disabled:opacity-50",
          )}
        >
          <Plus className="h-4 w-4" />
          New session
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-3 py-2">
        <div className="space-y-0.5">
          {sessions.map((s) => (
            <div
              key={s.session_id}
              className={cn(
                "group flex items-start rounded-lg transition-colors",
                s.session_id === activeSessionId
                  ? "bg-accent text-accent-foreground"
                  : "text-foreground/80 hover:bg-muted",
              )}
            >
              <button
                onClick={() => onSelect(s.session_id)}
                className="flex flex-1 items-start gap-2.5 px-3 py-2 text-left min-w-0"
              >
                <MessageSquare className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-mono">
                    {s.session_id}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {formatTime(s.last_active)}
                    {s.channel_type !== "web" && s.channel_type !== "cli"
                      ? ` · ${s.channel_type}`
                      : ""}
                  </div>
                </div>
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(s.session_id);
                }}
                title="Delete session"
                className={cn(
                  "shrink-0 rounded-md p-1.5 mr-1 mt-1.5 transition-colors",
                  "text-muted-foreground/0 group-hover:text-muted-foreground",
                  "hover:!text-destructive hover:bg-destructive/10",
                )}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          {sessions.length === 0 && !loading && (
            <p className="px-3 py-4 text-center text-xs text-muted-foreground">
              No sessions yet
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
