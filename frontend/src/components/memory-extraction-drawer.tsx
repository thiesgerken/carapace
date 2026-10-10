"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Loader2, MessageSquare, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { MemoryProvenanceList } from "@/components/memory-ui";
import { getMemorySession } from "@/lib/api";
import { formatAbsoluteTime } from "@/lib/format-time";
import type { MemoryExtractionRecord, MemoryFact, MemoryFactCategory, MemorySessionDetail } from "@/lib/types";

const FACT_CATEGORIES: readonly MemoryFactCategory[] = ["user", "social", "surroundings"];

export function sessionEventHref(sessionId: string, seq: number): string {
  return `/?session=${encodeURIComponent(sessionId)}&event=${seq}`;
}

interface MemoryExtractionDrawerProps {
  server: string;
  sessionId: string;
  onClose: () => void;
}

export function MemoryExtractionDrawer({ server, sessionId, onClose }: MemoryExtractionDrawerProps) {
  const t = useTranslations("memory.drawer");
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const [detail, setDetail] = useState<MemorySessionDetail | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  useEffect(() => {
    let cancelled = false;
    getMemorySession(server, sessionId)
      .then((result) => {
        if (!cancelled) setDetail(result);
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : String(loadError));
      });
    return () => {
      cancelled = true;
    };
  }, [server, sessionId]);

  const title = detail?.session.title?.trim() || sessionId;

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      aria-labelledby="memory-drawer-title"
      className="m-0 ml-auto h-dvh max-h-none w-[min(40rem,100vw)] max-w-none border-l border-border bg-background p-0 text-foreground shadow-xl backdrop:bg-black/40"
    >
      <div className="flex h-full flex-col">
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 id="memory-drawer-title" className="truncate text-lg font-semibold tracking-tight">{title}</h2>
            <Link href={`/?session=${encodeURIComponent(sessionId)}`} className="mt-1 inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
              <MessageSquare className="h-3.5 w-3.5" />
              {t("openSession")}
            </Link>
          </div>
          <button
            type="button"
            onClick={() => dialogRef.current?.close()}
            aria-label={t("close")}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-4">
          {error ? (
            <p className="text-sm text-destructive">{error}</p>
          ) : detail === undefined ? (
            <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
          ) : detail === null ? (
            <p className="text-sm text-muted-foreground">{t("notEligible")}</p>
          ) : (
            <>
              {detail.current ? (
                <ExtractionRecord record={detail.current} sessionId={sessionId} linkSources />
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t("notExtracted")}
                  {detail.session.task ? ` ${t("taskStatus", { status: detail.session.task.status })}` : null}
                </p>
              )}
              {detail.history.length > 0 ? (
                <section className="space-y-2">
                  <h3 className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">{t("history")}</h3>
                  {detail.history.map((record) => (
                    <HistoryEntry key={record.id} record={record} sessionId={sessionId} />
                  ))}
                </section>
              ) : null}
            </>
          )}
        </div>
      </div>
    </dialog>
  );
}

function HistoryEntry({ record, sessionId }: { record: MemoryExtractionRecord; sessionId: string }) {
  const locale = useLocale();
  return (
    <details className="rounded-lg border border-border px-3 py-2">
      <summary className="cursor-pointer text-sm">
        <span className="font-mono text-xs">{record.provenance.model} · {record.provenance.prompt_version}</span>
        <span className="ml-2 text-xs text-muted-foreground">{formatAbsoluteTime(record.created_at, locale)}</span>
      </summary>
      <div className="pt-3">
        {/* Rewinds reuse event seqs, so an older version's sources may point at different events now. */}
        <ExtractionRecord record={record} sessionId={sessionId} linkSources={false} />
      </div>
    </details>
  );
}

function ExtractionRecord({ record, sessionId, linkSources }: { record: MemoryExtractionRecord; sessionId: string; linkSources: boolean }) {
  const t = useTranslations("memory.drawer");
  const { extraction } = record;
  const lists: [string, string[]][] = [
    [t("outcomes"), extraction.outcomes],
    [t("openLoops"), extraction.open_loops],
    [t("onMyMind"), extraction.on_my_mind],
    [t("friction"), extraction.friction],
  ];

  return (
    <div className="space-y-4 text-sm">
      <p className="leading-relaxed">{extraction.abstract}</p>

      {extraction.tags.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {extraction.tags.map((tag) => (
            <span key={tag} className="rounded-full bg-accent px-2 py-0.5 font-mono text-[11px] text-accent-foreground">{tag}</span>
          ))}
        </div>
      ) : null}

      {lists.filter(([, items]) => items.length > 0).map(([label, items]) => (
        <section key={label}>
          <h4 className="mb-1 text-xs font-medium text-muted-foreground">{label}</h4>
          <ul className="list-disc space-y-0.5 pl-5">
            {items.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>
      ))}

      {FACT_CATEGORIES.map((category) => {
        const facts = extraction.facts.filter((fact) => fact.category === category);
        if (facts.length === 0) return null;
        return (
          <section key={category}>
            <h4 className="mb-1 text-xs font-medium text-muted-foreground">{t(`factCategories.${category}`)}</h4>
            <ul className="space-y-2">
              {facts.map((fact) => (
                <FactItem key={`${fact.statement}-${fact.subject}`} fact={fact} sessionId={sessionId} linkSources={linkSources} />
              ))}
            </ul>
          </section>
        );
      })}

      <section>
        <h4 className="mb-1 text-xs font-medium text-muted-foreground">{t("provenance")}</h4>
        <MemoryProvenanceList provenance={record.provenance} />
      </section>
    </div>
  );
}

function FactItem({ fact, sessionId, linkSources }: { fact: MemoryFact; sessionId: string; linkSources: boolean }) {
  const t = useTranslations("memory.drawer");
  const locale = useLocale();
  const meta = [
    fact.subject,
    t(`confidence.${fact.confidence}`),
    t(`durability.${fact.durability}`),
    fact.valid_until ? t("validUntil", { date: new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(Date.parse(fact.valid_until)) }) : null,
    t(`sourceKind.${fact.source_kind}`),
  ].filter(Boolean);

  return (
    <li className="rounded-lg border border-border/70 px-3 py-2">
      <div>{fact.statement}</div>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
        <span>{meta.join(" · ")}</span>
        {fact.source_seqs.map((seq) => linkSources ? (
          <Link
            key={seq}
            href={sessionEventHref(sessionId, seq)}
            // Inside the chat view the drawer would otherwise stay open over the event it just linked to.
            onClick={(event) => event.currentTarget.closest("dialog")?.close()}
            className="font-mono underline underline-offset-2 hover:text-foreground"
          >
            #{seq}
          </Link>
        ) : (
          <span key={seq} className="font-mono">#{seq}</span>
        ))}
      </div>
    </li>
  );
}
