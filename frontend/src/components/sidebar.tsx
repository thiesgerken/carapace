"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Archive, ArchiveRestore, Bot, Loader2, Lock, Mail, MessageSquare, Pin, Save, Search, Star, Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { EmojiText } from "@/components/emoji-text";
import { useAppLocale } from "@/components/locale-provider";
import { NewSessionButton, type NewSessionOptions } from "@/components/new-session-button";
import { SandboxUsageBanner } from "@/components/sandbox-usage-banner";
import { SidebarFooter } from "@/components/sidebar-footer";
import { agentIcon } from "@/hooks/use-brand";
import { useSessionSearch, type SessionSearchMode } from "@/hooks/use-session-search";
import type { AuthUserInfo } from "@/lib/api";
import type { SandboxUsage, SessionAttributesPatch, SessionInfo, SessionSandboxSnapshot, SessionSearchHit } from "@/lib/types";
import {
  canArchiveSession,
  cn,
  formatBytes,
  sandboxStatusIndicatorClass,
  sandboxStatusKey,
  shouldConfirmArchiveSession,
  sessionHasKnowledgeChanges,
  splitOnMatches,
} from "@/lib/utils";

interface SidebarProps {
  server: string;
  token: string;
  sessions: SessionInfo[];
  sandboxUsage?: SandboxUsage | null;
  showArchivedSessions?: boolean;
  activeSessionId: string | null;
  frontendVersion?: string | null;
  backendVersion?: string | null;
  currentUser?: AuthUserInfo | null;
  onSelect: (sessionId: string) => void;
  onNew: (options?: NewSessionOptions) => void;
  /** Called before every action that navigates, e.g. to close the mobile drawer. */
  onNavigate: () => void;
  onUpdateAttributes: (sessionId: string, attributes: SessionAttributesPatch) => Promise<SessionInfo>;
  onDelete: (sessionId: string, options?: { skipUnpushedWarning?: boolean }) => Promise<void>;
  onDisconnect: () => void;
  githubUrl: string;
  loading?: boolean;
  hasMore?: boolean;
  loadingMore?: boolean;
  onLoadMore?: () => void;
}

type SessionGroup = {
  key: string;
  label: string;
  sessions: SessionInfo[];
  sortValue: number;
};

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

function runSidebarAttributeUpdate(promise: Promise<unknown>): void {
  void promise.catch(() => {
    // Sidebar actions currently fail silently like delete; avoid unhandled rejections.
  });
}

const SEARCH_MODES: readonly SessionSearchMode[] = ["title", "fulltext"];

function HighlightedText({ text, query }: { text: string; query: string }) {
  return splitOnMatches(text, query).map((part, index) => (
    part.match ? (
      <mark key={index} className="rounded-sm bg-primary/20 px-0.5 text-foreground">
        {part.text}
      </mark>
    ) : (
      <span key={index}>{part.text}</span>
    )
  ));
}

export function Sidebar({
  server,
  token,
  sessions,
  sandboxUsage = null,
  showArchivedSessions = true,
  activeSessionId,
  frontendVersion = null,
  backendVersion = null,
  currentUser = null,
  onSelect,
  onNew,
  onNavigate,
  onUpdateAttributes,
  onDelete,
  onDisconnect,
  githubUrl,
  loading,
  hasMore = false,
  loadingMore = false,
  onLoadMore,
}: SidebarProps) {
  const t = useTranslations();
  const tSidebar = useTranslations("sidebar");
  const { locale } = useAppLocale();
  const scrollRootRef = useRef<HTMLDivElement | null>(null);
  const loadMoreRef = useRef<HTMLDivElement | null>(null);
  const [referenceTime, setReferenceTime] = useState<number>(() => Date.now());
  const [searchQuery, setSearchQuery] = useState("");
  const [searchMode, setSearchMode] = useState<SessionSearchMode>("title");
  const [searchRevision, setSearchRevision] = useState(0);
  const search = useSessionSearch(server, token, searchQuery, searchMode, searchRevision);
  const searchHits = search.hits;
  const searching = searchHits !== null;
  const activeSessions = sessions.filter((session) => !session.attributes.archived);
  const archivedSessions = showArchivedSessions
    ? sessions.filter((session) => session.attributes.archived)
    : [];

  /** Row actions change hits the parent's session list may not hold (archived ones), so the search re-runs. */
  function refreshSearch(): void {
    setSearchRevision((revision) => revision + 1);
  }

  function updateAttributes(sessionId: string, attributes: SessionAttributesPatch): void {
    runSidebarAttributeUpdate(onUpdateAttributes(sessionId, attributes).then(refreshSearch));
  }

  useEffect(() => {
    const updateReferenceTime = (): void => {
      setReferenceTime(Date.now());
    };

    updateReferenceTime();
    const intervalId = window.setInterval(updateReferenceTime, 60_000);
    return () => {
      window.clearInterval(intervalId);
    };
  }, []);

  function calendarDayNumber(date: Date): number {
    return Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86_400_000);
  }

  function groupSessionsByAge(sectionSessions: SessionInfo[]): SessionGroup[] {
    const groupedSessions = {
      today: [] as SessionInfo[],
      yesterday: [] as SessionInfo[],
      last7Days: [] as SessionInfo[],
      last30Days: [] as SessionInfo[],
      unknown: [] as SessionInfo[],
    };
    const monthGroups = new Map<string, SessionGroup>();
    const now = new Date(referenceTime);
    const todayDayNumber = calendarDayNumber(now);
    const currentYear = now.getFullYear();
    const monthFormatter = new Intl.DateTimeFormat(locale, { month: "long" });
    const monthYearFormatter = new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" });

    for (const session of sectionSessions) {
      const parsed = Date.parse(session.last_active);
      if (Number.isNaN(parsed)) {
        groupedSessions.unknown.push(session);
        continue;
      }

      const sessionDate = new Date(parsed);
      const dayDiff = todayDayNumber - calendarDayNumber(sessionDate);

      if (dayDiff <= 0) {
        groupedSessions.today.push(session);
        continue;
      }

      if (dayDiff === 1) {
        groupedSessions.yesterday.push(session);
        continue;
      }

      if (dayDiff <= 7) {
        groupedSessions.last7Days.push(session);
        continue;
      }

      if (dayDiff <= 30) {
        groupedSessions.last30Days.push(session);
        continue;
      }

      const year = sessionDate.getFullYear();
      const month = sessionDate.getMonth();
      const key = `${year}-${month}`;
      const existingGroup = monthGroups.get(key);
      if (existingGroup) {
        existingGroup.sessions.push(session);
        continue;
      }

      monthGroups.set(key, {
        key,
        label: year === currentYear ? monthFormatter.format(sessionDate) : monthYearFormatter.format(sessionDate),
        sessions: [session],
        sortValue: year * 12 + month,
      });
    }

    const groups: SessionGroup[] = [
      {
        key: "today",
        label: tSidebar("sections.today"),
        sessions: groupedSessions.today,
        sortValue: Number.MAX_SAFE_INTEGER,
      },
      {
        key: "yesterday",
        label: tSidebar("sections.yesterday"),
        sessions: groupedSessions.yesterday,
        sortValue: Number.MAX_SAFE_INTEGER - 1,
      },
      {
        key: "last7Days",
        label: tSidebar("sections.last7Days"),
        sessions: groupedSessions.last7Days,
        sortValue: Number.MAX_SAFE_INTEGER - 2,
      },
      {
        key: "last30Days",
        label: tSidebar("sections.last30Days"),
        sessions: groupedSessions.last30Days,
        sortValue: Number.MAX_SAFE_INTEGER - 3,
      },
      ...[...monthGroups.values()].sort((left, right) => right.sortValue - left.sortValue),
      {
        key: "unknown",
        label: tSidebar("sections.unknownDate"),
        sessions: groupedSessions.unknown,
        sortValue: Number.MIN_SAFE_INTEGER,
      },
    ];

    return groups.filter((group) => group.sessions.length > 0);
  }

  function formatTime(iso: string): string {
    const parsed = Date.parse(iso);
    if (Number.isNaN(parsed)) {
      return iso;
    }

    const diff = referenceTime - parsed;
    if (diff < 60_000) return tSidebar("time.justNow");

    const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
    if (diff < 3_600_000) return formatter.format(-Math.floor(diff / 60_000), "minute");
    if (diff < 86_400_000) return formatter.format(-Math.floor(diff / 3_600_000), "hour");
    if (diff < 604_800_000) return formatter.format(-Math.floor(diff / 86_400_000), "day");

    return new Intl.DateTimeFormat(locale, {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(parsed);
  }

  function shouldConfirmSessionDeletion(
    session: Pick<SessionInfo, "message_count">,
    event: { shiftKey: boolean },
  ): boolean {
    return session.message_count === 0
      || shouldConfirmDestructiveAction(
        event,
        tSidebar("confirm.deleteSession"),
      );
  }

  useEffect(() => {
    if (searching || !hasMore || !onLoadMore) return;
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
  }, [hasMore, onLoadMore, searching, sessions.length]);

  function renderSessionSection(sectionSessions: SessionInfo[]) {
    return (
      <div className="space-y-0.5">
        {sectionSessions.map((session) => renderSessionRow(session))}
      </div>
    );
  }

  function renderSessionGroups(sectionSessions: SessionInfo[]) {
    const pinnedSessions = sectionSessions.filter((session) => session.attributes.pinned);
    const unpinnedSessions = sectionSessions.filter((session) => !session.attributes.pinned);

    return [
      pinnedSessions.length > 0 ? (
        <div key="pinned">{renderSessionSection(pinnedSessions)}</div>
      ) : null,
      pinnedSessions.length > 0 && unpinnedSessions.length > 0 ? (
        <div
          key="pinned-separator"
          className="mx-3 my-2 h-px bg-gradient-to-r from-transparent via-border to-transparent"
          aria-hidden="true"
        />
      ) : null,
      ...groupSessionsByAge(unpinnedSessions).map((group) => (
      <div key={group.key}>
        <div className="px-3 pb-1 text-xs font-medium text-muted-foreground">
          {group.label}
        </div>
        {renderSessionSection(group.sessions)}
      </div>
      )),
    ];
  }

  function renderSearchResults(hits: SessionSearchHit[]) {
    if (search.failed || hits.length === 0) {
      const message = search.failed
        ? tSidebar("search.failed")
        : search.loading ? tSidebar("search.searching") : tSidebar("search.noResults");
      return <p className="px-3 py-4 text-center text-xs text-muted-foreground">{message}</p>;
    }
    return (
      <div className="space-y-0.5">
        {hits.map((hit) => renderSessionRow(hit.session, hit.snippet))}
      </div>
    );
  }

  /** `snippet` is the match excerpt of a fulltext search hit, shown under the title. */
  function renderSessionRow(session: SessionInfo, snippet?: string | null) {
    const sandbox = sandboxSummary(session);
    const sandboxLabel = sandbox ? sandboxSummaryLabel(sandbox) : null;
    const sessionCanArchive = canArchiveSession(session);
    const showPrivateIcon = session.attributes.private;
    const showSavedIcon = !session.attributes.private
      && !!session.knowledge_last_committed_at
      && !sessionHasKnowledgeChanges(session);
    const showKnowledgeIndicator = showPrivateIcon || showSavedIcon;
    const showUnattendedIcon = session.attributes.unattended;
    const channelLabel = session.channel_type !== "web" && session.channel_type !== "cli"
      ? session.channel_type
      : null;
    const lastActiveLabel = formatTime(session.last_active);
    const messageCountLabel = tSidebar("messageCount", { count: session.message_count });
    const hasSandboxInfo = !!sandbox;
    const selectSession = (): void => {
      onNavigate();
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
            ? "bg-primary/10 text-foreground"
            : "text-foreground/80 hover:bg-muted",
        )}
      >
        <div className="flex w-full min-w-0 items-start gap-2.5 px-3 pt-2 pb-1 text-left">
          <MessageSquare className={cn("mt-0.5 h-4 w-4 shrink-0", session.session_id === activeSessionId ? "text-primary" : "text-muted-foreground")} />
          <div className="min-w-0 flex-1 truncate text-sm font-medium" title={session.title || session.session_id}>
              {session.title ? (
                <EmojiText text={session.title} />
              ) : (
                <span className="font-mono break-all">{session.session_id}</span>
              )}
          </div>
          {showUnattendedIcon ? (
            <span
              className="mt-0.5 inline-flex shrink-0 items-center text-muted-foreground"
              title={tSidebar("unattendedSession")}
            >
              <Bot className="h-3.5 w-3.5" />
              <span className="sr-only">{tSidebar("unattendedSession")}</span>
            </span>
          ) : null}
        </div>
        {snippet ? (
          <div className="line-clamp-2 break-words px-3 pb-1 text-xs text-muted-foreground">
            <HighlightedText text={snippet} query={search.hitsQuery} />
          </div>
        ) : null}
        <div className="flex items-start gap-2 px-3 pb-2">
          <div className="min-w-0 flex-1 text-left">
            {hasSandboxInfo ? (
              <div className="space-y-0.5 text-xs text-muted-foreground">
                <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                  <span className="inline-flex items-center gap-1.5">
                    <span
                      title={t(`chatView.sandbox.status.${sandboxStatusKey(sandbox.status)}`)}
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
                    title={messageCountLabel}
                  >
                    <span>{session.message_count}</span>
                    <Mail className="mt-px h-3 w-3 shrink-0" />
                    <span className="sr-only">{messageCountLabel}</span>
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
                      title={showPrivateIcon ? tSidebar("privateSession") : (session.knowledge_last_archive_path ?? tSidebar("knowledgeCommitted"))}
                    >
                      {showPrivateIcon ? <Lock className="mt-px h-3 w-3 shrink-0" /> : <Save className="mt-px h-3 w-3 shrink-0" />}
                      <span className="sr-only">{showPrivateIcon ? tSidebar("privateSession") : tSidebar("knowledgeCommitted")}</span>
                    </span>
                  ) : null}
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted-foreground">
                <span
                  className="inline-flex items-center gap-1"
                  title={messageCountLabel}
                >
                  <span>{session.message_count}</span>
                  <Mail className="mt-px h-3 w-3 shrink-0" />
                  <span className="sr-only">{messageCountLabel}</span>
                </span>
                <span aria-hidden="true">·</span>
                <span>{lastActiveLabel}</span>
                {channelLabel ? <span aria-hidden="true">·</span> : null}
                {channelLabel ? <span>{channelLabel}</span> : null}
                {showKnowledgeIndicator ? <span aria-hidden="true">·</span> : null}
                {showKnowledgeIndicator ? (
                  <span
                    className="inline-flex items-center"
                    title={showPrivateIcon ? tSidebar("privateSession") : (session.knowledge_last_archive_path ?? tSidebar("knowledgeCommitted"))}
                  >
                    {showPrivateIcon ? <Lock className="mt-px h-3 w-3 shrink-0" /> : <Save className="mt-px h-3 w-3 shrink-0" />}
                    <span className="sr-only">{showPrivateIcon ? tSidebar("privateSession") : tSidebar("knowledgeCommitted")}</span>
                  </span>
                ) : null}
              </div>
            )}
          </div>
          <div className="session-row-actions flex shrink-0 items-center gap-1 self-start">
          <button
            onClick={(event) => {
              event.stopPropagation();
              updateAttributes(session.session_id, { pinned: !session.attributes.pinned });
            }}
            title={session.attributes.pinned ? tSidebar("actions.unpin") : tSidebar("actions.pin")}
            className={cn(
              "session-row-action-button rounded-md p-1.5 transition-colors",
              session.attributes.pinned && "session-row-action-active",
              session.attributes.pinned
                ? "text-primary hover:bg-muted"
                : "text-muted-foreground/0 group-hover:text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Pin className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={(event) => {
              event.stopPropagation();
              updateAttributes(session.session_id, { favorite: !session.attributes.favorite });
            }}
            title={session.attributes.favorite ? tSidebar("actions.unfavorite") : tSidebar("actions.favorite")}
            className={cn(
              "session-row-action-button rounded-md p-1.5 transition-colors",
              session.attributes.favorite && "session-row-action-active",
              session.attributes.favorite
                ? "text-primary hover:bg-muted"
                : "text-muted-foreground/0 group-hover:text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Star className="h-3.5 w-3.5" />
          </button>
          {session.attributes.archived || sessionCanArchive ? (
            <button
              onClick={(event) => {
                event.stopPropagation();
                const nextArchived = !session.attributes.archived;
                if (
                  nextArchived
                  && shouldConfirmArchiveSession(session)
                  && !shouldConfirmDestructiveAction(
                    event,
                    tSidebar("confirm.archiveSession"),
                  )
                ) {
                  return;
                }
                updateAttributes(session.session_id, { archived: nextArchived });
              }}
              title={session.attributes.archived ? tSidebar("actions.unarchive") : [tSidebar("actions.archive"), tSidebar("actions.shiftSkip")].join("\n")}
              className={cn(
                "session-row-action-button rounded-md p-1.5 transition-colors",
                session.attributes.archived && "session-row-action-active",
                session.attributes.archived
                  ? "text-muted-foreground hover:bg-muted hover:text-foreground"
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
          ) : null}
          <button
            onClick={(event) => {
              event.stopPropagation();
              if (!shouldConfirmSessionDeletion(session, event)) {
                return;
              }
              void onDelete(session.session_id, { skipUnpushedWarning: event.shiftKey }).then(refreshSearch);
            }}
            title={session.message_count === 0
              ? tSidebar("actions.deleteEmpty")
              : [tSidebar("actions.delete"), tSidebar("actions.shiftSkip")].join("\n")}
            className={cn(
              "session-row-action-button rounded-md p-1.5 transition-colors",
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
      <div className="flex items-center gap-2 px-4 py-3">
        <Link
          href="/"
          onClick={onNavigate}
          className="flex min-w-0 items-center gap-1.5 rounded-sm text-sm font-semibold leading-none tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <Image src={agentIcon(currentUser?.agentIcon)} alt="" width={18} height={18} aria-hidden="true" className="shrink-0" />
          <span className="truncate">{currentUser?.agentName?.trim() || t("app.name")}</span>
        </Link>
      </div>

      {/* New session button */}
      <div className="px-3 pt-1 pb-1">
        <NewSessionButton
          onCreate={(options) => {
            onNavigate();
            onNew(options);
          }}
          disabled={loading}
          fullWidth
        />
      </div>

      {/* Session search */}
      <div className="px-3 pt-1 pb-1">
        <div className="flex items-center gap-1.5 rounded-lg border border-border bg-background pl-2.5 pr-1 focus-within:ring-2 focus-within:ring-ring">
          {search.loading ? (
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" aria-hidden="true" />
          ) : (
            <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          )}
          <input
            type="text"
            enterKeyHint="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape" && searchQuery) {
                event.preventDefault();
                setSearchQuery("");
              }
            }}
            placeholder={tSidebar("search.placeholder")}
            aria-label={tSidebar("search.placeholder")}
            className="min-w-0 flex-1 bg-transparent py-1.5 text-base outline-none placeholder:text-muted-foreground sm:text-sm"
          />
          {searchQuery ? (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              title={tSidebar("search.clear")}
              aria-label={tSidebar("search.clear")}
              className="shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          ) : null}
          <div
            role="radiogroup"
            aria-label={tSidebar("search.mode")}
            className="flex shrink-0 rounded-md bg-muted p-0.5 text-[11px] font-medium"
          >
            {SEARCH_MODES.map((mode) => (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={searchMode === mode}
                title={tSidebar(`search.${mode}Hint`)}
                onClick={() => setSearchMode(mode)}
                className={cn(
                  "rounded px-1.5 py-0.5 transition-colors",
                  searchMode === mode
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {tSidebar(`search.${mode}`)}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Session list */}
      <div ref={scrollRootRef} className="flex-1 overflow-y-auto px-3 py-2">
        <div className="space-y-4">
          <SandboxUsageBanner usage={sandboxUsage} />
          {searching ? renderSearchResults(searchHits) : (
            <>
              {renderSessionGroups(activeSessions)}
              {archivedSessions.length > 0 ? (
                <div className="space-y-4">
                  <div className="px-3 pb-1 text-xs font-medium text-muted-foreground">
                    {tSidebar("sections.archived")}
                  </div>
                  {renderSessionGroups(archivedSessions)}
                </div>
              ) : null}
              {sessions.length === 0 && !loading && (
                <p className="px-3 py-4 text-center text-xs text-muted-foreground">
                  {tSidebar("empty")}
                </p>
              )}
              {hasMore || loadingMore ? (
                <div ref={loadMoreRef} className="px-3 py-2">
                  {loadingMore ? (
                    <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      {tSidebar("loadingMore")}
                    </div>
                  ) : (
                    <div className="h-4" aria-hidden="true" />
                  )}
                </div>
              ) : null}
            </>
          )}
        </div>
      </div>

      <SidebarFooter
        server={server}
        token={token}
        currentUser={currentUser}
        frontendVersion={frontendVersion}
        backendVersion={backendVersion}
        githubUrl={githubUrl}
        onNavigate={onNavigate}
        onDisconnect={onDisconnect}
      />
    </div>
  );
}
