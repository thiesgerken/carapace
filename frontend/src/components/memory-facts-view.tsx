"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { sessionEventHref } from "@/components/memory-extraction-drawer";
import { useMemoryStatus } from "@/components/memory-status";
import { controlClassName } from "@/components/memory-ui";
import { listMemoryFacts } from "@/lib/api";
import { factMatchesText, groupFacts, isExpiredFact, type FactGroup } from "@/lib/memory";
import type {
  MemoryConfidence,
  MemoryDurability,
  MemoryFactCategory,
  MemoryFactFilter,
  MemoryFactListResponse,
  MemoryFactSourceKind,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const CATEGORIES: readonly MemoryFactCategory[] = ["user", "social", "surroundings"];
const CONFIDENCES: readonly MemoryConfidence[] = ["high", "medium", "low"];
const DURABILITIES: readonly MemoryDurability[] = ["durable", "dated"];
const SOURCE_KINDS: readonly MemoryFactSourceKind[] = ["user_said", "observed"];

interface FactFilterForm {
  confidence: MemoryConfidence | "";
  durability: MemoryDurability | "";
  sourceKind: MemoryFactSourceKind | "";
  /** Month key from <input type="month">. */
  period: string;
}

const DEFAULT_FORM: FactFilterForm = { confidence: "", durability: "", sourceKind: "", period: "" };

export function MemoryFactsView({ server }: { server: string }) {
  const t = useTranslations("memory.facts");
  const tFact = useTranslations("memory.drawer");
  const { status } = useMemoryStatus();
  const [category, setCategory] = useState<MemoryFactCategory>("user");
  const [form, setForm] = useState(DEFAULT_FORM);
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<MemoryFactListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const filter = useMemo<MemoryFactFilter>(() => ({
    category: [category],
    confidence: form.confidence ? [form.confidence] : null,
    durability: form.durability ? [form.durability] : null,
    source_kind: form.sourceKind ? [form.sourceKind] : null,
    period: form.period || null,
  }), [category, form]);

  // `status` changes on every poll and after every action; see MemoryStatusProvider.
  useEffect(() => {
    let cancelled = false;
    listMemoryFacts(server, filter)
      .then((result) => {
        if (cancelled) return;
        setResponse(result);
        setError(null);
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : String(loadError));
      });
    return () => {
      cancelled = true;
    };
  }, [server, filter, status]);

  const groups = useMemo(
    () => groupFacts(response?.items ?? []).filter((group) => factMatchesText(group, query)),
    [response, query],
  );
  const today = new Date().toISOString().slice(0, 10);
  const bySubject = category === "social"
    ? [...groups.reduce((bySubjectMap, group) => {
      const subject = group.latest.subject?.trim() || t("noSubject");
      return bySubjectMap.set(subject, [...(bySubjectMap.get(subject) ?? []), group]);
    }, new Map<string, FactGroup[]>())].sort(([a], [b]) => a.localeCompare(b))
    : [["", groups] as const];

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label={t("category")} className="inline-flex rounded-lg border border-border bg-background p-0.5">
            {CATEGORIES.map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={category === value}
                onClick={() => setCategory(value)}
                className={cn(
                  "rounded-md px-3 py-1 text-sm font-medium transition-colors",
                  category === value ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {tFact(`factCategories.${value}`)}
              </button>
            ))}
          </div>
          <select aria-label={t("filters.confidence")} value={form.confidence} onChange={(event) => setForm({ ...form, confidence: event.target.value as FactFilterForm["confidence"] })} className={controlClassName}>
            <option value="">{t("filters.anyConfidence")}</option>
            {CONFIDENCES.map((value) => <option key={value} value={value}>{tFact(`confidence.${value}`)}</option>)}
          </select>
          <select aria-label={t("filters.durability")} value={form.durability} onChange={(event) => setForm({ ...form, durability: event.target.value as FactFilterForm["durability"] })} className={controlClassName}>
            <option value="">{t("filters.anyDurability")}</option>
            {DURABILITIES.map((value) => <option key={value} value={value}>{tFact(`durability.${value}`)}</option>)}
          </select>
          <select aria-label={t("filters.sourceKind")} value={form.sourceKind} onChange={(event) => setForm({ ...form, sourceKind: event.target.value as FactFilterForm["sourceKind"] })} className={controlClassName}>
            <option value="">{t("filters.anySourceKind")}</option>
            {SOURCE_KINDS.map((value) => <option key={value} value={value}>{tFact(`sourceKind.${value}`)}</option>)}
          </select>
          <input
            type="month"
            aria-label={t("filters.month")}
            title={t("filters.month")}
            value={form.period}
            onChange={(event) => setForm({ ...form, period: event.target.value })}
            className={controlClassName}
          />
          <input
            type="search"
            aria-label={t("filters.text")}
            placeholder={t("filters.text")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className={cn(controlClassName, "min-w-40 flex-1")}
          />
        </div>

        {error ? <div className="rounded-lg border border-border bg-background px-4 py-2 text-sm text-destructive">{error}</div> : null}

        {response === null && error === null ? (
          <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
        ) : groups.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border bg-background/80 px-4 py-6 text-sm text-muted-foreground">{t("empty")}</p>
        ) : bySubject.map(([subject, subjectGroups]) => (
          <section key={subject} className="space-y-2">
            {subject ? <h3 className="pt-2 text-sm font-semibold">{subject}</h3> : null}
            <ul className="space-y-2">
              {subjectGroups.map((group) => <FactGroupItem key={group.key} group={group} expired={isExpiredFact(group.latest, today)} />)}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

function FactGroupItem({ group, expired }: { group: FactGroup; expired: boolean }) {
  const t = useTranslations("memory.facts");
  const tFact = useTranslations("memory.drawer");
  const locale = useLocale();
  const { latest } = group;
  const meta = [
    latest.category !== "social" ? latest.subject : null,
    tFact(`confidence.${latest.confidence}`),
    tFact(`durability.${latest.durability}`),
    latest.valid_until ? tFact("validUntil", { date: new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(Date.parse(latest.valid_until)) }) : null,
    tFact(`sourceKind.${latest.source_kind}`),
    group.firstSeen === group.lastSeen ? group.firstSeen : t("seen", { first: group.firstSeen, last: group.lastSeen }),
  ].filter(Boolean);

  return (
    <li className={cn("rounded-lg border border-border bg-background px-3 py-2 text-sm", expired && "opacity-50")} title={expired ? t("expired") : undefined}>
      <div className={cn(expired && "line-through decoration-muted-foreground/60")}>{latest.statement}</div>
      <div className="mt-1 text-xs text-muted-foreground">{meta.join(" · ")}</div>
      <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
        {group.occurrences.map((fact) => (
          <li key={fact.id}>
            <Link href={`/memory/sessions?session=${encodeURIComponent(fact.session_id)}`} className="hover:text-foreground hover:underline">
              {fact.session_title?.trim() || fact.session_id}
            </Link>
            {fact.source_seqs.map((seq) => (
              <Link key={seq} href={sessionEventHref(fact.session_id, seq)} className="ml-1 font-mono underline-offset-2 hover:text-foreground hover:underline">
                #{seq}
              </Link>
            ))}
          </li>
        ))}
      </ul>
    </li>
  );
}
