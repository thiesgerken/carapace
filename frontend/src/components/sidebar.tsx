"use client";

import { Lock, LogOut, MessageSquare, Plus, Save, Trash2 } from "lucide-react";
import { EmojiText } from "@/components/emoji-text";
import type { SessionInfo, SessionSandboxSnapshot } from "@/lib/types";
import {
  cn,
  formatBytes,
  sandboxStatusIndicatorClass,
  sandboxStatusLabel,
  sessionHasKnowledgeChanges,
} from "@/lib/utils";

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
  return d.toLocaleDateString(undefined, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function sandboxSummary(session: SessionInfo): SessionSandboxSnapshot | null {
  const sandbox = session.sandbox;
  if (!sandbox || sandbox.status === "missing") return null;
  return sandbox;
}

function sandboxSummaryLabel(sandbox: SessionSandboxSnapshot): string | null {
  if (typeof sandbox.last_measured_used_bytes === "number") {
    return formatBytes(sandbox.last_measured_used_bytes);
  }
  return null;
}

function formatMessageCount(count: number): string {
  return `${count} ${count === 1 ? "msg" : "msgs"}`;
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
          className="rounded-md p-2 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
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
            (() => {
              const sandbox = sandboxSummary(s);
              const sandboxLabel = sandbox ? sandboxSummaryLabel(sandbox) : null;
              const showPrivateIcon = s.private;
              const showSavedIcon = !s.private && !!s.knowledge_last_committed_at && !sessionHasKnowledgeChanges(s);
              const showKnowledgeIndicator = showPrivateIcon || showSavedIcon;
              const messageCountLabel = formatMessageCount(s.message_count);
              const activityLabel = [
                formatTime(s.last_active),
                s.channel_type !== "web" && s.channel_type !== "cli"
                  ? s.channel_type
                  : null,
              ]
                .filter(Boolean)
                .join(" · ");
              return (
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
                  <div
                    className="truncate text-sm"
                    title={s.title || s.session_id}
                  >
                    {s.title ? (
                      <EmojiText text={s.title} />
                    ) : (
                      <span className="font-mono break-all">
                        {s.session_id}
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted-foreground">
                    {sandbox ? (
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          title={sandboxStatusLabel(sandbox.status)}
                          className={cn(
                            "h-1.5 w-1.5 shrink-0 rounded-full",
                            sandboxStatusIndicatorClass(sandbox.status),
                          )}
                        />
                        {sandboxLabel ? <span>{sandboxLabel}</span> : null}
                      </span>
                    ) : null}
                    {sandbox && sandboxLabel ? <span aria-hidden="true">·</span> : null}
                    <span>{messageCountLabel}</span>
                    <span aria-hidden="true">·</span>
                    <span>{activityLabel}</span>
                    {showKnowledgeIndicator ? <span aria-hidden="true">·</span> : null}
                    {showKnowledgeIndicator ? (
                      <span
                        className="inline-flex items-center"
                        title={showPrivateIcon ? "Private session" : (s.knowledge_last_archive_path ?? "All changes committed to knowledge")}
                      >
                        {showPrivateIcon ? <Lock className="h-3 w-3" /> : <Save className="h-3 w-3" />}
                        <span className="sr-only">{showPrivateIcon ? "Private session" : "All changes committed to knowledge"}</span>
                      </span>
                    ) : null}
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
              );
            })()
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
