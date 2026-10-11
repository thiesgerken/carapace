"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { ArrowRight, Check, CircleAlert, Clock, RefreshCw, ShieldAlert, Wallet, type LucideIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { ChatInput } from "@/components/chat-input";
import { SessionOptionsDropdown, type NewSessionOptions } from "@/components/new-session-button";
import { periodHref } from "@/components/memory-period-detail";
import { getHome, setOpenLoopDismissed } from "@/lib/api";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/format-time";
import { formatUsd, weekLabel } from "@/lib/memory";
import { saveChatDraft } from "@/lib/storage";
import type { HomeData, HomeNotices, HomeOpenLoop, HomeThisWeek } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Draft key of the home composer; session ids never take this form. */
const HOME_DRAFT_KEY = "home";

const sessionHref = (sessionId: string): string => `/?session=${encodeURIComponent(sessionId)}`;

function useHomeData(server: string): { data: HomeData | null; error: string | null } {
  const [data, setData] = useState<HomeData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getHome(server)
      .then((home) => {
        if (!cancelled) setData(home);
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : String(loadError));
      });
    return () => {
      cancelled = true;
    };
  }, [server]);

  return { data, error };
}

/**
 * The landing page without an open session: a composer that starts one, and what memory knows is
 * still open. All memory text is model output derived from tool output, so it renders as plain text
 * and every link is built from ids, never from the text.
 */
export function HomeView({ server, agentName, onStart }: {
  server: string;
  agentName: string;
  /** Creates a session and sends `content` into it; resolves to false when creating failed. */
  onStart: (content: string, options: NewSessionOptions) => Promise<boolean>;
}) {
  const t = useTranslations("home");
  const { data, error } = useHomeData(server);
  const [options, setOptions] = useState<NewSessionOptions>({});
  const [starting, setStarting] = useState(false);
  // Remounting the composer is how a draft restored after a failed start shows up again.
  const [composerKey, setComposerKey] = useState(0);

  async function start(content: string): Promise<void> {
    setStarting(true);
    const started = await onStart(content, options);
    setStarting(false);
    if (!started) {
      saveChatDraft(HOME_DRAFT_KEY, content);
      setComposerKey((key) => key + 1);
    }
  }

  const hasMemory = data !== null && (data.open_loops.length > 0 || data.this_week !== null);
  const thisWeek = data && hasMemory ? <ThisWeekBlock week={data.this_week} /> : null;

  // The chat view's frame: a column with the composer pinned at its foot, and the inspector's 22rem
  // on the right from lg up, so the composer stays put when the started session takes over.
  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-clip">
      <div className="min-h-0 flex flex-1 flex-col lg:grid lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-h-0 flex flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            <div className="mx-auto max-w-3xl space-y-4">
              {data ? <NoticeChips notices={data.notices} /> : null}
              {error ? (
                <p className="text-sm text-destructive">{error}</p>
              ) : data === null ? null : hasMemory ? (
                <>
                  <Block title={t("openLoops.title")}>
                    <OpenLoopList server={server} loops={data.open_loops} />
                  </Block>
                  <div className="lg:hidden">{thisWeek}</div>
                </>
              ) : (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  {t.rich("noMemory", { link: (chunks) => <Link href="/memory" className="underline underline-offset-2 hover:text-foreground">{chunks}</Link> })}
                </p>
              )}
            </div>
          </div>
          <ChatInput
            key={composerKey}
            sessionId={HOME_DRAFT_KEY}
            onSend={(content) => void start(content)}
            connected
            disabled={starting}
            agentName={agentName}
            accessory={(
              <SessionOptionsDropdown
                options={options}
                onChange={setOptions}
                disabled={starting}
                openUpward
                className="rounded-lg border-0 bg-transparent p-2 text-muted-foreground"
              />
            )}
          />
        </div>
        <aside className="hidden min-h-0 border-l border-border bg-muted/20 lg:block">
          <div className="h-full overflow-y-auto p-3">{thisWeek}</div>
        </aside>
      </div>
    </div>
  );
}

function ThisWeekBlock({ week }: { week: HomeThisWeek | null }) {
  const t = useTranslations("home");
  return (
    <Block title={t("thisWeek.title")} action={week ? <PeriodLink periodKey={week.period_key} /> : null}>
      {week ? <ThisWeek week={week} /> : <p className="text-sm text-muted-foreground">{t("thisWeek.empty")}</p>}
    </Block>
  );
}

function Block({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-border bg-background/88 p-4 shadow-sm sm:p-5">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** How long a dismissed loop can still be brought back. */
const UNDO_MS = 6000;

/**
 * Dismissing hides a loop at once and keeps an undo row in its place for a few seconds; the server
 * call runs meanwhile, and a failure brings the loop back with the error.
 */
function OpenLoopList({ server, loops }: { server: string; loops: HomeOpenLoop[] }) {
  const t = useTranslations("home.openLoops");
  // Absent: open. "undo": dismissed, undo row showing. "gone": dismissed for good.
  const [phases, setPhases] = useState<ReadonlyMap<string, "undo" | "gone">>(new Map());
  const [restoredId, setRestoredId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const frame = useRef<HTMLDivElement>(null);
  // The last request per loop: a quick Undo must not reach the server before its dismissal.
  const requests = useRef(new Map<string, Promise<void>>());

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach(clearTimeout);
  }, []);

  function setPhase(id: string, phase: "undo" | "gone" | null): void {
    setPhases((current) => {
      const next = new Map(current);
      if (phase === null) next.delete(id);
      else next.set(id, phase);
      return next;
    });
  }

  function stopTimer(id: string): void {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
  }

  function request(id: string, dismissed: boolean): Promise<void> {
    const previous = requests.current.get(id) ?? Promise.resolve();
    // A failed predecessor is already reported by its own caller; the next request runs regardless.
    const next = previous.catch(() => {}).then(() => setOpenLoopDismissed(server, id, dismissed));
    requests.current.set(id, next);
    return next;
  }

  function dismiss(loop: HomeOpenLoop): void {
    setError(null);
    setRestoredId(null);
    setPhase(loop.id, "undo");
    timers.current.set(loop.id, setTimeout(() => {
      timers.current.delete(loop.id);
      // The undo button is about to vanish; keep keyboard focus inside the block.
      if (document.activeElement?.getAttribute("data-undo-id") === loop.id) frame.current?.focus();
      setPhase(loop.id, "gone");
    }, UNDO_MS));
    request(loop.id, true).catch((dismissError: unknown) => {
      stopTimer(loop.id);
      setPhase(loop.id, null);
      setError(dismissError instanceof Error ? dismissError.message : String(dismissError));
    });
  }

  function undo(loop: HomeOpenLoop): void {
    stopTimer(loop.id);
    setError(null);
    setPhase(loop.id, null);
    setRestoredId(loop.id);
    request(loop.id, false).catch((undoError: unknown) => {
      setPhase(loop.id, "gone");
      setError(undoError instanceof Error ? undoError.message : String(undoError));
    });
  }

  const visible = loops.filter((loop) => phases.get(loop.id) !== "gone");

  return (
    <div ref={frame} tabIndex={-1} className="space-y-2 outline-none">
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
      {visible.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      ) : (
        <ul className="divide-y divide-border/60">
          {visible.map((loop) => (
            <li key={loop.id} className="group/loop py-3 first:pt-0 last:pb-0">
              {phases.get(loop.id) === "undo" ? (
                <div role="status" className="flex items-center gap-3 text-sm text-muted-foreground">
                  <span aria-hidden="true" className={cn(checkCircleClassName, "border-[#236b86] bg-[#236b86] text-white dark:border-sky-400 dark:bg-sky-400 dark:text-background")}>
                    <Check className="h-3 w-3" strokeWidth={3} />
                  </span>
                  <span className="min-w-0 flex-1 truncate">{t("dismissed", { text: loop.text })}</span>
                  <button
                    type="button"
                    data-undo-id={loop.id}
                    autoFocus
                    onClick={() => undo(loop)}
                    className="shrink-0 rounded-md px-1.5 py-0.5 font-medium text-[#236b86] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:text-sky-400"
                  >
                    {t("undo")}
                  </button>
                </div>
              ) : (
                <OpenLoopItem loop={loop} focusDismiss={loop.id === restoredId} onDismiss={() => dismiss(loop)} />
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The to-do circle: hollow while open, filled once dismissed (in the undo row). */
const checkCircleClassName = "mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition-colors";

function OpenLoopItem({ loop, focusDismiss, onDismiss }: { loop: HomeOpenLoop; focusDismiss: boolean; onDismiss: () => void }) {
  const t = useTranslations("home");
  const locale = useLocale();
  const [now] = useState(() => Date.now());

  return (
    <div className="flex items-start gap-3">
      <button
        type="button"
        onClick={onDismiss}
        autoFocus={focusDismiss}
        aria-label={t("openLoops.dismiss")}
        title={t("openLoops.dismiss")}
        className={cn(
          checkCircleClassName,
          "group/check border-muted-foreground/40 text-[#236b86] dark:text-sky-400",
          // A 20px circle, but a 44px tap target (the inset counts from inside the 2px border).
          "relative after:absolute after:-inset-3.5 after:content-['']",
          "hover:border-[#236b86] focus-visible:border-[#236b86] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:hover:border-sky-400 dark:focus-visible:border-sky-400",
        )}
      >
        {/* The check previews on hover and focus; touch screens have neither and tap straight to done. */}
        <Check aria-hidden="true" className="h-3 w-3 opacity-0 transition-opacity group-hover/check:opacity-100 group-focus-visible/check:opacity-100" strokeWidth={3} />
      </button>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:flex-row sm:items-start sm:gap-4">
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-sm leading-relaxed">{loop.text}</p>
          <p className="truncate text-xs text-muted-foreground">
            {loop.session_title ?? t("untitledSession")}
            {" · "}
            <time dateTime={loop.session_last_active} title={formatAbsoluteTime(loop.session_last_active, locale)}>
              {formatRelativeTime(loop.session_last_active, locale, now, t("justNow"))}
            </time>
          </p>
        </div>
        <Link
          href={sessionHref(loop.session_id)}
          className="inline-flex shrink-0 items-center gap-1 self-start text-sm font-medium text-[#236b86] hover:underline dark:text-sky-400"
        >
          {t("openLoops.continue")}
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  );
}

function ThisWeek({ week }: { week: HomeThisWeek }) {
  const t = useTranslations("home");

  if (week.source === "sessions") {
    return (
      <ul className="space-y-3">
        {week.sessions.map((session) => (
          <li key={session.session_id} className="space-y-0.5">
            <Link href={sessionHref(session.session_id)} className="text-sm font-medium hover:underline">
              {session.title ?? t("untitledSession")}
            </Link>
            <p className="text-sm leading-relaxed text-muted-foreground">{session.abstract}</p>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <div className="space-y-4">
      {week.themes.length > 0 ? (
        <ul className="space-y-1.5 text-sm leading-relaxed">
          {week.themes.map((theme) => <li key={theme.theme}>{theme.theme}</li>)}
        </ul>
      ) : null}
      {week.highlights.length > 0 ? (
        <div className="space-y-1.5">
          <h3 className="text-xs font-medium text-muted-foreground">{t("thisWeek.highlights")}</h3>
          <ul className="list-disc space-y-1 pl-4 text-sm leading-relaxed marker:text-muted-foreground">
            {week.highlights.map((highlight) => <li key={highlight}>{highlight}</li>)}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function PeriodLink({ periodKey }: { periodKey: string }) {
  const locale = useLocale();
  return (
    <Link href={periodHref(periodKey)} className="text-xs text-muted-foreground hover:text-foreground hover:underline" title={weekLabel(periodKey, locale, true)}>
      {periodKey.slice(5)} · {weekLabel(periodKey, locale, false)}
    </Link>
  );
}

function NoticeChips({ notices }: { notices: HomeNotices }) {
  const t = useTranslations("home.notices");
  const locale = useLocale();
  const approvals = notices.pending_approvals;
  const budget = notices.memory_budget;

  const chips: { key: string; href: string; icon: LucideIcon; label: string; urgent: boolean }[] = [];
  if (approvals.length > 0) {
    chips.push({
      key: "approvals",
      href: sessionHref(approvals[0].session_id),
      icon: ShieldAlert,
      label: approvals.length === 1
        ? t("approval", { title: approvals[0].session_title ?? t("untitledSession") })
        : t("approvals", { count: approvals.length }),
      urgent: true,
    });
  }
  if (notices.failed_memory_tasks > 0) {
    chips.push({ key: "failed", href: "/memory/tasks?status=failed", icon: CircleAlert, label: t("failedTasks", { count: notices.failed_memory_tasks }), urgent: true });
  }
  if (notices.outdated_memory_records > 0) {
    chips.push({ key: "outdated", href: "/memory/timeline", icon: RefreshCw, label: t("outdatedRecords", { count: notices.outdated_memory_records }), urgent: false });
  }
  if (budget) {
    chips.push({
      key: "budget",
      href: "/settings/account#memory",
      icon: budget.window === "day" ? Clock : Wallet,
      label: t(budget.window === "day" ? "budgetDay" : "budgetMonth", { used: formatUsd(budget.used_usd, locale), limit: formatUsd(budget.limit_usd, locale) }),
      urgent: false,
    });
  }
  if (chips.length === 0) return null;

  return (
    <ul className="flex flex-wrap gap-2">
      {chips.map(({ key, href, icon: Icon, label, urgent }) => (
        <li key={key}>
          <Link
            href={href}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors",
              urgent
                ? "border-amber-500/40 bg-amber-500/10 text-amber-800 hover:bg-amber-500/15 dark:text-amber-300"
                : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Icon aria-hidden="true" className="h-3.5 w-3.5" />
            {label}
          </Link>
        </li>
      ))}
    </ul>
  );
}
