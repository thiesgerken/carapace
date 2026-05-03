"use client";

import { useEffect, useRef } from "react";
import { Archive, ArchiveRestore, Loader2, Lock, LogOut, Mail, MessageSquare, Pin, Plus, Save, Star, Trash2 } from "lucide-react";
import { EmojiText } from "@/components/emoji-text";
import type { SessionAttributesPatch, SessionInfo, SessionSandboxSnapshot } from "@/lib/types";
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
  onUpdateAttributes: (sessionId: string, attributes: SessionAttributesPatch) => Promise<SessionInfo>;
  onDelete: (sessionId: string) => void;
  onDisconnect: () => void;
  loading?: boolean;
  hasMore?: boolean;
  loadingMore?: boolean;
  onLoadMore?: () => void;
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

function shouldConfirmDestructiveAction(event: { shiftKey: boolean }, confirmation: string): boolean {
  return event.shiftKey || window.confirm(confirmation);
}

function runSidebarAttributeUpdate(promise: Promise<SessionInfo>): void {
  void promise.catch(() => {
    // Sidebar actions currently fail silently like delete; avoid unhandled rejections.
  });
}

export function Sidebar({
  sessions,
  activeSessionId,
  onSelect,
  onNew,
  onUpdateAttributes,
  onDelete,
  onDisconnect,
  loading,
  hasMore = false,
  loadingMore = false,
  onLoadMore,
}: SidebarProps) {
  const scrollRootRef = useRef<HTMLDivElement | null>(null);
  const loadMoreRef = useRef<HTMLDivElement | null>(null);
  const activeSessions = sessions.filter((session) => !session.attributes.archived);
  const archivedSessions = sessions.filter((session) => session.attributes.archived);

  useEffect(() => {
    if (!hasMore || !onLoadMore) return;
    const root = scrollRootRef.current;
    const target = loadMoreRef.current;
    if (!root || !target) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) {
          return;
        }
        onLoadMore();
      },
      { root, rootMargin: "160px 0px" },
    );

    observer.observe(target);
    return () => {
      observer.disconnect();
    };
  }, [hasMore, onLoadMore, sessions.length]);

  function renderSessionSection(sectionSessions: SessionInfo[]) {
    const pinnedSessions = sectionSessions.filter((session) => session.attributes.pinned);
    const unpinnedSessions = sectionSessions.filter((session) => !session.attributes.pinned);

    return (
      <div className="space-y-0.5">
        {pinnedSessions.map(renderSessionRow)}
        {pinnedSessions.length > 0 && unpinnedSessions.length > 0 ? (
          <div className="mx-3 my-1 border-t border-border/50" aria-hidden="true" />
        ) : null}
        {unpinnedSessions.map(renderSessionRow)}
      </div>
    );
  }

  function renderSessionRow(session: SessionInfo) {
    const sandbox = sandboxSummary(session);
    const sandboxLabel = sandbox ? sandboxSummaryLabel(sandbox) : null;
    const showPrivateIcon = session.attributes.private;
    const showSavedIcon = !session.attributes.private
      && !!session.knowledge_last_committed_at
      && !sessionHasKnowledgeChanges(session);
    const showKnowledgeIndicator = showPrivateIcon || showSavedIcon;
    const channelLabel = session.channel_type !== "web" && session.channel_type !== "cli"
      ? session.channel_type
      : null;
    const lastActiveLabel = formatTime(session.last_active);
    const hasSandboxInfo = !!sandbox;
    const selectSession = (): void => {
      onSelect(session.session_id);
    };
    const handleRowKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }
      event.preventDefault();
      selectSession();
    };

    return (
      <div
        key={session.session_id}
        role="button"
        tabIndex={0}
        onClick={selectSession}
        onKeyDown={handleRowKeyDown}
        aria-pressed={session.session_id === activeSessionId}
        className={cn(
          "group cursor-pointer rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          session.session_id === activeSessionId
            ? "bg-accent text-accent-foreground"
            : "text-foreground/80 hover:bg-muted",
        )}
      >
        <div className="flex w-full min-w-0 items-start gap-2.5 px-3 pt-2 pb-1 text-left">
          <MessageSquare className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1 truncate text-sm" title={session.title || session.session_id}>
              {session.title ? (
                <EmojiText text={session.title} />
              ) : (
                <span className="font-mono break-all">{session.session_id}</span>
              )}
          </div>
        </div>
        <div className="flex items-start gap-2 px-3 pb-2">
          <div className="min-w-0 flex-1 text-left">
            {hasSandboxInfo ? (
              <div className="space-y-0.5 text-xs text-muted-foreground">
                <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
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
                  {sandboxLabel ? <span aria-hidden="true">·</span> : null}
                  <span
                    className="inline-flex items-center gap-1"
                    title={`${session.message_count} ${session.message_count === 1 ? "message" : "messages"}`}
                  >
                    <span>{session.message_count}</span>
                    <Mail className="mt-px h-3 w-3 shrink-0" />
                    <span className="sr-only">{session.message_count === 1 ? "message" : "messages"}</span>
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                  <span>{lastActiveLabel}</span>
                  {channelLabel ? <span aria-hidden="true">·</span> : null}
                  {channelLabel ? <span>{channelLabel}</span> : null}
                  {showKnowledgeIndicator ? <span aria-hidden="true">·</span> : null}
                  {showKnowledgeIndicator ? (
                    <span
                      className="inline-flex items-center"
                      title={showPrivateIcon ? "Private session" : (session.knowledge_last_archive_path ?? "All changes committed to knowledge")}
                    >
                      {showPrivateIcon ? <Lock className="mt-px h-3 w-3 shrink-0" /> : <Save className="mt-px h-3 w-3 shrink-0" />}
                      <span className="sr-only">{showPrivateIcon ? "Private session" : "All changes committed to knowledge"}</span>
                    </span>
                  ) : null}
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted-foreground">
                <span
                  className="inline-flex items-center gap-1"
                  title={`${session.message_count} ${session.message_count === 1 ? "message" : "messages"}`}
                >
                  <span>{session.message_count}</span>
                  <Mail className="mt-px h-3 w-3 shrink-0" />
                  <span className="sr-only">{session.message_count === 1 ? "message" : "messages"}</span>
                </span>
                <span aria-hidden="true">·</span>
                <span>{lastActiveLabel}</span>
                {channelLabel ? <span aria-hidden="true">·</span> : null}
                {channelLabel ? <span>{channelLabel}</span> : null}
                {showKnowledgeIndicator ? <span aria-hidden="true">·</span> : null}
                {showKnowledgeIndicator ? (
                  <span
                    className="inline-flex items-center"
                    title={showPrivateIcon ? "Private session" : (session.knowledge_last_archive_path ?? "All changes committed to knowledge")}
                  >
                    {showPrivateIcon ? <Lock className="mt-px h-3 w-3 shrink-0" /> : <Save className="mt-px h-3 w-3 shrink-0" />}
                    <span className="sr-only">{showPrivateIcon ? "Private session" : "All changes committed to knowledge"}</span>
                  </span>
                ) : null}
              </div>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1 self-start">
          <button
            onClick={(event) => {
              event.stopPropagation();
              runSidebarAttributeUpdate(onUpdateAttributes(session.session_id, { pinned: !session.attributes.pinned }));
            }}
            title={session.attributes.pinned ? "Unpin session" : "Pin session"}
            className={cn(
              "rounded-md p-1.5 transition-colors",
              session.attributes.pinned
                ? "text-sky-700 hover:bg-sky-100"
                : "text-muted-foreground/0 group-hover:text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Pin className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={(event) => {
              event.stopPropagation();
              runSidebarAttributeUpdate(onUpdateAttributes(session.session_id, { favorite: !session.attributes.favorite }));
            }}
            title={session.attributes.favorite ? "Remove favorite" : "Favorite session"}
            className={cn(
              "rounded-md p-1.5 transition-colors",
              session.attributes.favorite
                ? "text-amber-700 hover:bg-amber-100"
                : "text-muted-foreground/0 group-hover:text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Star className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={(event) => {
              event.stopPropagation();
              const nextArchived = !session.attributes.archived;
              if (
                nextArchived
                && !shouldConfirmDestructiveAction(
                  event,
                  "Archive this session? It will leave the default list, reset its sandbox, and stay in the knowledge repo.",
                )
              ) {
                return;
              }
              runSidebarAttributeUpdate(onUpdateAttributes(session.session_id, { archived: nextArchived }));
            }}
            title={session.attributes.archived ? "Unarchive session" : ["Archive session", "Shift+click to skip confirmation"].join("\n")}
            className={cn(
              "rounded-md p-1.5 transition-colors",
              session.attributes.archived
                ? "text-violet-700 group-hover:text-emerald-900 hover:bg-emerald-100"
                : "text-muted-foreground/0 group-hover:text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {session.attributes.archived ? (
              <>
                <Archive className="h-3.5 w-3.5 group-hover:hidden" />
                <ArchiveRestore className="hidden h-3.5 w-3.5 group-hover:block" />
              </>
            ) : <Archive className="h-3.5 w-3.5" />}
          </button>
          <button
            onClick={(event) => {
              event.stopPropagation();
              if (!shouldConfirmDestructiveAction(event, "Delete this session? Chat history and sandbox state will be removed.")) {
                return;
              }
              onDelete(session.session_id);
            }}
            title={["Delete session", "Shift+click to skip confirmation"].join("\n")}
            className={cn(
              "rounded-md p-1.5 transition-colors",
              "text-muted-foreground/0 group-hover:text-muted-foreground",
              "hover:!text-destructive hover:bg-destructive/10",
            )}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <span className="text-sm font-semibold tracking-tight">carapace</span>
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
      <div ref={scrollRootRef} className="flex-1 overflow-y-auto px-3 py-2">
        <div className="space-y-4">
          {renderSessionSection(activeSessions)}
          {archivedSessions.length > 0 ? (
            <div>
              <div className="px-3 pb-1 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                Archived
              </div>
              {renderSessionSection(archivedSessions)}
            </div>
          ) : null}
          {sessions.length === 0 && !loading && (
            <p className="px-3 py-4 text-center text-xs text-muted-foreground">
              No sessions yet
            </p>
          )}
          {hasMore || loadingMore ? (
            <div ref={loadMoreRef} className="px-3 py-2">
              {loadingMore ? (
                <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Loading more sessions
                </div>
              ) : (
                <div className="h-4" aria-hidden="true" />
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
