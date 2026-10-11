"use client";

import Link from "next/link";
import { ChevronRight, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { FACT_CATEGORIES, FactItem, type MemorySessionDetailState } from "@/components/memory-extraction-detail";
import { TaskStatusBadge } from "@/components/memory-ui";
import { UNFINISHED_TASK_STATUSES } from "@/lib/memory";
import type { MemorySessionDetail } from "@/lib/types";
import { cn } from "@/lib/utils";

const chevronClassName = "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform";

/**
 * The session's extraction in the chat inspector, collapsed to its status line by default so the
 * inspector's other cards stay in view. Rendered twice (desktop column and mobile sheet), so the
 * open state lives in the caller. Sessions memory doesn't cover (private, excluded jobs) get nothing.
 */
export function ChatMemorySection({ sessionId, state, open, onOpenChange, onSourceNavigate }: {
  sessionId: string;
  state: MemorySessionDetailState;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSourceNavigate?: () => void;
}) {
  const t = useTranslations("chatView.memory");
  const tFact = useTranslations("memory.drawer");
  const { detail, error } = state;
  if (detail === null) return null;

  const extraction = detail?.current?.extraction;

  return (
    <details
      data-memory-section
      open={open}
      onToggle={(event) => onOpenChange(event.currentTarget.open)}
      className="group/card rounded-2xl border border-border/70 bg-background/90 p-3 shadow-sm"
    >
      <summary className="flex cursor-pointer list-none items-start justify-between gap-2 [&::-webkit-details-marker]:hidden">
        <div className="min-w-0 space-y-1">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{t("title")}</div>
          {error ? (
            <div className="text-xs text-destructive">{error}</div>
          ) : detail === undefined ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
          ) : (
            <StatusLine detail={detail} />
          )}
        </div>
        <ChevronRight aria-hidden="true" className={cn(chevronClassName, "mt-0.5 group-open/card:rotate-90")} />
      </summary>

      {detail ? (
        <div className="mt-3 space-y-3 border-t border-border/60 pt-3 text-sm">
          {extraction ? <p className="leading-relaxed">{extraction.abstract}</p> : null}
          {extraction ? FACT_CATEGORIES.map((category) => {
            const facts = extraction.facts.filter((fact) => fact.category === category);
            if (facts.length === 0) return null;
            return (
              <details key={category} className="group/category">
                <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground [&::-webkit-details-marker]:hidden">
                  <ChevronRight aria-hidden="true" className={cn(chevronClassName, "group-open/category:rotate-90")} />
                  {tFact(`factCategories.${category}`)}
                  <span className="tabular-nums">· {facts.length}</span>
                </summary>
                <ul className="mt-2 space-y-2">
                  {facts.map((fact) => (
                    <FactItem key={`${fact.statement}-${fact.subject}`} fact={fact} sessionId={sessionId} linkSources onSourceNavigate={onSourceNavigate} />
                  ))}
                </ul>
              </details>
            );
          }) : null}
          <Link
            href={`/memory/sessions?session=${encodeURIComponent(sessionId)}`}
            className="inline-block text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            {t("openInMemory")}
          </Link>
        </div>
      ) : null}
    </details>
  );
}

function StatusLine({ detail }: { detail: MemorySessionDetail }) {
  const tStates = useTranslations("memory.sessions.states");
  const tReasons = useTranslations("memory.outdatedReasons");
  const { extraction: summary, task } = detail.session;
  const outdated = summary !== null && summary.outdated.length > 0;

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
      <span className={cn(summary === null ? "text-muted-foreground" : outdated ? "text-amber-700 dark:text-amber-400" : "text-[#236b86] dark:text-sky-400")}>
        {tStates(summary === null ? "missing" : outdated ? "outdated" : "current")}
        {outdated ? ` · ${summary.outdated.map((reason) => tReasons(reason)).join(", ")}` : null}
      </span>
      {task && UNFINISHED_TASK_STATUSES.includes(task.status) ? <TaskStatusBadge status={task.status} /> : null}
    </div>
  );
}
