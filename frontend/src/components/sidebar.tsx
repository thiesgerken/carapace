"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Archive, ArchiveRestore, Bot, BookOpen, Brain, Loader2, Lock, LogOut, Mail, MessageSquare, Pin, Save, Settings2, Star, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { EmojiText } from "@/components/emoji-text";
import { useAppLocale } from "@/components/locale-provider";
import { NewSessionButton, type NewSessionOptions } from "@/components/new-session-button";
import { GlobalGitIndicator, GlobalGitPanel, useGlobalGit } from "@/components/git-sync";
import { VersionBadge } from "@/components/version-badge";
import { agentIcon } from "@/hooks/use-brand";
import type { AuthUserInfo } from "@/lib/api";
import type { SessionAttributesPatch, SessionInfo, SessionSandboxSnapshot } from "@/lib/types";
import {
  canArchiveSession,
  cn,
  formatBytes,
  sandboxStatusIndicatorClass,
  sandboxStatusKey,
  shouldConfirmArchiveSession,
  sessionHasKnowledgeChanges,
} from "@/lib/utils";

interface SidebarProps {
  server: string;
  token: string;
  sessions: SessionInfo[];
  showArchivedSessions?: boolean;
  activeSessionId: string | null;
  frontendVersion?: string | null;
  backendVersion?: string | null;
  currentUser?: AuthUserInfo | null;
  onSelect: (sessionId: string) => void;
  onNew: (options?: NewSessionOptions) => void;
  onGoHome: () => void;
  onOpenSettings: () => void;
  onUpdateAttributes: (sessionId: string, attributes: SessionAttributesPatch) => Promise<SessionInfo>;
  onDelete: (sessionId: string, options?: { skipUnpushedWarning?: boolean }) => void;
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

function runSidebarAttributeUpdate(promise: Promise<SessionInfo>): void {
  void promise.catch(() => {
    // Sidebar actions currently fail silently like delete; avoid unhandled rejections.
  });
}

function accountInitial(user: AuthUserInfo | null | undefined): string {
  const label = user?.display_name?.trim() || user?.username.trim() || "?";
  return label.slice(0, 1).toLocaleUpperCase();
}

function GitHubIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={className}
      fill="currentColor"
    >
      <path d="M12 1.5C6.201 1.5 1.5 6.201 1.5 12c0 4.64 3.01 8.577 7.184 9.966.525.097.716-.228.716-.507 0-.25-.009-.913-.015-1.792-2.922.635-3.538-1.409-3.538-1.409-.478-1.213-1.168-1.536-1.168-1.536-.955-.652.072-.639.072-.639 1.056.074 1.611 1.084 1.611 1.084.939 1.608 2.463 1.144 3.063.875.095-.68.368-1.144.668-1.407-2.333-.265-4.785-1.166-4.785-5.192 0-1.147.41-2.085 1.082-2.82-.108-.266-.469-1.336.102-2.786 0 0 .882-.282 2.89 1.077A10.048 10.048 0 0 1 12 6.59c.892.004 1.79.121 2.629.355 2.006-1.359 2.887-1.077 2.887-1.077.573 1.45.212 2.52.104 2.786.674.735 1.08 1.673 1.08 2.82 0 4.036-2.456 4.924-4.797 5.184.378.325.714.965.714 1.946 0 1.406-.013 2.54-.013 2.886 0 .282.189.609.723.506A10.503 10.503 0 0 0 22.5 12c0-5.799-4.701-10.5-10.5-10.5Z" />
    </svg>
  );
}

export function Sidebar({
  server,
  token,
  sessions,
  showArchivedSessions = true,
  activeSessionId,
  frontendVersion = null,
  backendVersion = null,
  currentUser = null,
  onSelect,
  onNew,
  onGoHome,
  onOpenSettings,
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
  const accountMenuRef = useRef<HTMLDivElement | null>(null);
  const globalGit = useGlobalGit(server, token);
  const [referenceTime, setReferenceTime] = useState<number>(() => Date.now());
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const activeSessions = sessions.filter((session) => !session.attributes.archived);
  const archivedSessions = showArchivedSessions
    ? sessions.filter((session) => session.attributes.archived)
    : [];
  const accountName = currentUser?.display_name?.trim() || currentUser?.username || t("account.unknown");
  const accountUsername = currentUser?.username ?? t("account.unknown");

  function handleOpenSettings(): void {
    setAccountMenuOpen(false);
    onOpenSettings();
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

  useEffect(() => {
    if (!accountMenuOpen) return;

    function handlePointerDown(event: MouseEvent): void {
      const target = event.target;
      if (!(target instanceof Node) || accountMenuRef.current?.contains(target)) {
        return;
      }
      setAccountMenuOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") {
        setAccountMenuOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [accountMenuOpen]);

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
    return (
      <div className="space-y-0.5">
        {sectionSessions.map(renderSessionRow)}
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
        <div className="px-3 pb-1 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
          {group.label}
        </div>
        {renderSessionSection(group.sessions)}
      </div>
      )),
    ];
  }

  function renderSessionRow(session: SessionInfo) {
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
          <div className="min-w-0 flex-1 truncate text-sm font-medium" title={session.title || session.session_id}>
              {session.title ? (
                <EmojiText text={session.title} />
              ) : (
                <span className="font-mono break-all">{session.session_id}</span>
              )}
          </div>
          {showUnattendedIcon ? (
            <span
              className="mt-0.5 inline-flex shrink-0 items-center text-emerald-700"
              title={tSidebar("unattendedSession")}
            >
              <Bot className="h-3.5 w-3.5" />
              <span className="sr-only">{tSidebar("unattendedSession")}</span>
            </span>
          ) : null}
        </div>
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
              runSidebarAttributeUpdate(onUpdateAttributes(session.session_id, { pinned: !session.attributes.pinned }));
            }}
            title={session.attributes.pinned ? tSidebar("actions.unpin") : tSidebar("actions.pin")}
            className={cn(
              "session-row-action-button rounded-md p-1.5 transition-colors",
              session.attributes.pinned && "session-row-action-active",
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
            title={session.attributes.favorite ? tSidebar("actions.unfavorite") : tSidebar("actions.favorite")}
            className={cn(
              "session-row-action-button rounded-md p-1.5 transition-colors",
              session.attributes.favorite && "session-row-action-active",
              session.attributes.favorite
                ? "text-amber-700 hover:bg-amber-100"
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
                runSidebarAttributeUpdate(onUpdateAttributes(session.session_id, { archived: nextArchived }));
              }}
              title={session.attributes.archived ? tSidebar("actions.unarchive") : [tSidebar("actions.archive"), tSidebar("actions.shiftSkip")].join("\n")}
              className={cn(
                "session-row-action-button rounded-md p-1.5 transition-colors",
                session.attributes.archived && "session-row-action-active",
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
          ) : null}
          <button
            onClick={(event) => {
              event.stopPropagation();
              if (!shouldConfirmSessionDeletion(session, event)) {
                return;
              }
              onDelete(session.session_id, { skipUnpushedWarning: event.shiftKey });
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
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <div className="flex min-w-0 items-center gap-1.5 leading-none">
            <Image src={agentIcon(currentUser?.agentIcon)} alt="" width={18} height={18} aria-hidden="true" className="shrink-0" />
            <button
              type="button"
              onClick={onGoHome}
              title={t("navigation.home")}
              aria-label={t("navigation.home")}
              className="cursor-pointer rounded-sm text-sm font-semibold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              {currentUser?.agentName?.trim() || t("app.name")}
            </button>
          </div>
          <VersionBadge frontendVersion={frontendVersion} backendVersion={backendVersion} />
        </div>
        <div className="flex items-center gap-0.5">
          <Link
            href="/knowledge"
            title={t("navigation.knowledge")}
            aria-label={t("navigation.knowledge")}
            className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <BookOpen className="h-4 w-4" />
          </Link>
          <Link
            href="/memory"
            title={t("navigation.memory")}
            aria-label={t("navigation.memory")}
            className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <Brain className="h-4 w-4" />
          </Link>
          <button
            type="button"
            onClick={handleOpenSettings}
            title={t("navigation.settings")}
            aria-label={t("navigation.settings")}
            className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <Settings2 className="h-4 w-4" />
          </button>
          <div ref={accountMenuRef} className="relative">
            <button
              type="button"
              onClick={() => setAccountMenuOpen((open) => !open)}
              title={t("account.openMenu")}
              aria-label={t("account.openMenu")}
              aria-haspopup="menu"
              aria-expanded={accountMenuOpen}
              className="inline-flex h-8 max-w-[9.5rem] cursor-pointer items-center gap-2 rounded-sm text-xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <span
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border text-[11px] font-semibold transition-colors",
                  accountMenuOpen
                    ? "bg-accent text-accent-foreground"
                    : "bg-background text-muted-foreground",
                )}
              >
                {accountInitial(currentUser)}
              </span>
              <span className="truncate">{accountName}</span>
            </button>
            <GlobalGitIndicator git={globalGit} className="pointer-events-none absolute -right-0.5 -top-0.5" />

            {accountMenuOpen ? (
              <div
                role="menu"
                aria-label={t("account.menu")}
                className="absolute right-0 top-full z-50 mt-2 w-64 overflow-hidden rounded-lg border border-border bg-background text-foreground shadow-lg"
              >
                <div className="border-b border-border/80 px-3 py-3">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-sm font-semibold text-accent-foreground">
                      {accountInitial(currentUser)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium" title={accountName}>{accountName}</div>
                      <div className="truncate text-xs text-muted-foreground" title={accountUsername}>
                        {accountUsername}
                      </div>
                    </div>
                    <button
                      type="button"
                      role="menuitem"
                      title={t("account.logout")}
                      aria-label={t("account.logout")}
                      onClick={() => {
                        setAccountMenuOpen(false);
                        onDisconnect();
                      }}
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-destructive transition-colors hover:bg-destructive/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                    >
                      <LogOut className="h-4 w-4" />
                    </button>
                  </div>
                </div>
                {globalGit.configured !== false ? (
                  <GlobalGitPanel git={globalGit} className="border-b border-border/80 px-3 py-2.5" />
                ) : null}
                <div className="p-1">
                  <button
                    type="button"
                    role="menuitem"
                    onClick={handleOpenSettings}
                    className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm text-foreground transition-colors hover:bg-muted"
                  >
                    <Settings2 className="h-4 w-4 text-muted-foreground" />
                    {t("navigation.settings")}
                  </button>
                  <a
                    role="menuitem"
                    href={githubUrl}
                    target="_blank"
                    rel="noreferrer"
                    onClick={() => setAccountMenuOpen(false)}
                    className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm text-foreground transition-colors hover:bg-muted"
                  >
                    <GitHubIcon className="h-4 w-4 text-muted-foreground" />
                    {t("navigation.github")}
                  </a>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {/* New session button */}
      <div className="px-3 pt-3 pb-1">
        <NewSessionButton onCreate={onNew} disabled={loading} fullWidth />
      </div>

      {/* Session list */}
      <div ref={scrollRootRef} className="flex-1 overflow-y-auto px-3 py-2">
        <div className="space-y-4">
          {renderSessionGroups(activeSessions)}
          {archivedSessions.length > 0 ? (
            <div className="space-y-4">
              <div className="px-3 pb-1 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
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
        </div>
      </div>
    </div>
  );
}
