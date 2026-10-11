"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { MemoryProvenanceList } from "@/components/memory-ui";
import { getMemorySession } from "@/lib/api";
import { formatAbsoluteTime } from "@/lib/format-time";
import type { MemoryExtractionRecord, MemoryFact, MemoryFactCategory, MemorySessionDetail } from "@/lib/types";

const FACT_CATEGORIES: readonly MemoryFactCategory[] = ["user", "social", "surroundings"];

export function sessionEventHref(sessionId: string, seq: number): string {
  return `/?session=${encodeURIComponent(sessionId)}&event=${seq}`;
}

/** `detail` is undefined while loading and null when the session has no memory view (404). */
export interface MemorySessionDetailState {
  detail: MemorySessionDetail | null | undefined;
  error: string | null;
}

type Outcome = { sessionId: string } & ({ detail: MemorySessionDetail | null } | { error: string });

const IDLE: MemorySessionDetailState = { detail: undefined, error: null };

export function useMemorySessionDetail(server: string, sessionId: string | null): MemorySessionDetailState {
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  useEffect(() => {
    if (sessionId === null) return;
    let cancelled = false;
    getMemorySession(server, sessionId)
      .then((detail) => {
        if (!cancelled) setOutcome({ sessionId, detail });
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setOutcome({ sessionId, error: loadError instanceof Error ? loadError.message : String(loadError) });
      });
    return () => {
      cancelled = true;
    };
  }, [server, sessionId]);

  // Keyed by session: an outcome for another session reads as loading.
  if (outcome === null || outcome.sessionId !== sessionId) return IDLE;
  return "error" in outcome ? { detail: undefined, error: outcome.error } : { detail: outcome.detail, error: null };
}

/** The current extraction and earlier versions of one session; shared by the drawer and the sessions table. */
export function MemoryExtractionDetail({ sessionId, state, onSourceNavigate }: {
  sessionId: string;
  state: MemorySessionDetailState;
  /** Called when a fact source link is followed; see MemoryExtractionDrawer. */
  onSourceNavigate?: () => void;
}) {
  const t = useTranslations("memory.drawer");
  const { detail, error } = state;

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (detail === undefined) return <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />;
  if (detail === null) return <p className="text-sm text-muted-foreground">{t("notEligible")}</p>;

  return (
    <div className="space-y-6">
      {detail.current ? (
        <ExtractionRecord record={detail.current} sessionId={sessionId} linkSources onSourceNavigate={onSourceNavigate} />
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
    </div>
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

function ExtractionRecord({ record, sessionId, linkSources, onSourceNavigate }: {
  record: MemoryExtractionRecord;
  sessionId: string;
  linkSources: boolean;
  onSourceNavigate?: () => void;
}) {
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
                <FactItem key={`${fact.statement}-${fact.subject}`} fact={fact} sessionId={sessionId} linkSources={linkSources} onSourceNavigate={onSourceNavigate} />
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

function FactItem({ fact, sessionId, linkSources, onSourceNavigate }: {
  fact: MemoryFact;
  sessionId: string;
  linkSources: boolean;
  onSourceNavigate?: () => void;
}) {
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
            onClick={onSourceNavigate}
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
