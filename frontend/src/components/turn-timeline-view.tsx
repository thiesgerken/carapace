"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import {
  Archive,
  Box,
  ChevronRight,
  Circle,
  FileText,
  Flag,
  Globe,
  HardDrive,
  Hourglass,
  KeyRound,
  ListChecks,
  Loader2,
  Puzzle,
  Shield,
  ShieldCheck,
  Sparkles,
  Terminal,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { Stat } from "@/components/debug-stat";
import { useFormatCost } from "@/components/memory-ui";
import { useKeyedFetch } from "@/hooks/use-keyed-fetch";
import { useNow } from "@/hooks/use-now";
import { fetchLlmContext, fetchTurns, fetchTurnTimeline } from "@/lib/api";
import {
  llmSegments,
  outputRate,
  spanCategory,
  summarizeTurn,
  TIME_CATEGORIES,
  timelineRows,
  waterfallLines,
  type TimeCategory,
  type TimelineRow,
  type TimeBreakdown,
  type WaterfallLine,
} from "@/lib/turn-timeline";
import type { DebugRole, Span, SpanStatus, TurnSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const KIND_ICON: Record<string, LucideIcon> = {
  turn: Flag,
  "turn.prepare": ListChecks,
  llm: Sparkles,
  tool: Wrench,
  gate: Shield,
  sentinel: ShieldCheck,
  exec: Terminal,
  file: FileText,
  domain: Globe,
  sandbox: Box,
  skill: Puzzle,
  credential: KeyRound,
  wait: Hourglass,
  compaction: Archive,
  spill: HardDrive,
};

// The icon takes its span's bar color, a shade darker so it holds up as a glyph.
const CATEGORY_TEXT: Record<TimeCategory, string> = {
  preparation: "text-yellow-500 dark:text-yellow-200",
  llmWaiting: "text-sky-400 dark:text-sky-700",
  llmThinking: "text-violet-500 dark:text-violet-400",
  llmOutput: "text-sky-600 dark:text-sky-400",
  sentinel: "text-amber-600 dark:text-amber-400",
  sandbox: "text-emerald-600 dark:text-emerald-400",
  skill: "text-lime-600 dark:text-lime-400",
  execFile: "text-pink-600 dark:text-pink-400",
  credential: "text-teal-600 dark:text-teal-400",
  compaction: "text-orange-700 dark:text-orange-500",
  other: "text-slate-500 dark:text-slate-400",
  notCovered: "text-zinc-400 dark:text-zinc-500",
  userWait: "text-slate-500 dark:text-slate-400",
};

type Fact = { text: string; tone: "muted" | "good" | "warn" | "bad" };

const FACT_CLASS: Record<Fact["tone"], string> = {
  muted: "text-muted-foreground",
  good: "rounded bg-emerald-500/15 px-1 text-emerald-700 dark:text-emerald-300",
  warn: "rounded bg-amber-500/15 px-1 text-amber-700 dark:text-amber-300",
  bad: "rounded bg-red-500/15 px-1 text-red-700 dark:text-red-300",
};

const VERDICT_TONE: Record<string, Fact["tone"]> = { allow: "good", revise: "warn", escalate: "warn", deny: "bad" };

export const CATEGORY_CLASS: Record<TimeCategory, string> = {
  preparation: "bg-yellow-300 dark:bg-yellow-200",
  llmWaiting: "bg-sky-300 dark:bg-sky-800",
  llmThinking: "bg-violet-400 dark:bg-violet-500",
  llmOutput: "bg-sky-600 dark:bg-sky-400",
  sentinel: "bg-amber-500 dark:bg-amber-400",
  sandbox: "bg-emerald-500 dark:bg-emerald-400",
  skill: "bg-lime-500 dark:bg-lime-400",
  execFile: "bg-pink-500 dark:bg-pink-400",
  credential: "bg-teal-500 dark:bg-teal-400",
  compaction: "bg-orange-700 dark:bg-orange-600",
  other: "bg-slate-400 dark:bg-slate-500",
  notCovered: "bg-zinc-200 dark:bg-zinc-700",
  userWait: "bg-slate-400 dark:bg-slate-500",
};

// Waits on the user are hatched, so they read as "not the system's time" next to every color.
const HATCH: CSSProperties = { backgroundImage: "repeating-linear-gradient(135deg, transparent 0 3px, rgb(255 255 255 / 0.55) 3px 5px)" };

const STATUS_BAR_CLASS: Partial<Record<SpanStatus, string>> = {
  error: "bg-red-500 dark:bg-red-400",
  interrupted: "bg-zinc-400 dark:bg-zinc-600",
};

function useFormatDuration(): (ms: number) => string {
  const t = useTranslations("debugView.turns.duration");
  const format = useFormatter();
  return (ms) => {
    if (ms < 1000) return t("ms", { value: format.number(Math.round(ms)) });
    if (ms < 60_000) return t("s", { value: format.number(ms / 1000, { maximumFractionDigits: 1 }) });
    return t("min", { minutes: Math.floor(ms / 60_000), seconds: Math.floor((ms % 60_000) / 1000) });
  };
}

/**
 * A turn's spans as a waterfall with a summary of where its time went. Follows the newest turn live
 * until another one is picked. *revision* changes on the WebSocket notifications that make the turn list and the timeline stale.
 */
export function TurnTimelineView({
  server,
  token,
  sessionId,
  pickedTurn,
  onPickTurn,
  revision,
  onOpenRole,
}: {
  server: string;
  token: string;
  sessionId: string;
  /** Null follows the newest turn. */
  pickedTurn: string | null;
  onPickTurn: (turnId: string | null) => void;
  revision: string;
  onOpenRole: (role: DebugRole) => void;
}) {
  const t = useTranslations("debugView.turns");
  const loadTurns = useCallback(() => fetchTurns(server, token, sessionId), [server, token, sessionId]);
  const turns = useKeyedFetch(revision, loadTurns);
  const turnList = turns && "value" in turns ? turns.value : null;
  const newest = turnList?.at(-1)?.turn_id ?? null;
  const turnId = pickedTurn ?? newest;

  const loadTimeline = useCallback(() => fetchTurnTimeline(server, token, sessionId, turnId!), [server, token, sessionId, turnId]);
  const fetched = useKeyedFetch(turnId === null ? null : `${turnId}:${revision}`, loadTimeline);
  const timeline = fetched?.key.startsWith(`${turnId}:`) ? fetched : null;
  const shown = timeline && "value" in timeline ? timeline.value : null;

  if (turns && "error" in turns) return <p className="text-sm text-destructive">{t("loadError", { error: turns.error })}</p>;
  if (turnList === null) return <Loader2 className="mx-auto mt-8 h-5 w-5 animate-spin text-muted-foreground" />;
  if (turnList.length === 0) return <p className="text-sm text-muted-foreground">{t("empty")}</p>;

  return (
    <div className="flex flex-col gap-4">
      <TurnList turns={turnList} value={turnId} onChange={(value) => onPickTurn(value === newest ? null : value)} />
      {timeline && "error" in timeline ? (
        <p className="text-sm text-destructive">{t("timelineError", { error: timeline.error })}</p>
      ) : shown ? (
        <Timeline key={shown.turn.turn_id} turn={shown.turn} spans={shown.spans} server={server} token={token} sessionId={sessionId} onOpenRole={onOpenRole} />
      ) : (
        <Loader2 className="mx-auto mt-8 h-5 w-5 animate-spin text-muted-foreground" />
      )}
    </div>
  );
}

/** The turns as rows with a duration bar scaled to the longest one; running turns grow live. */
function TurnList({ turns, value, onChange }: { turns: TurnSummary[]; value: string | null; onChange: (turnId: string) => void }) {
  const t = useTranslations("debugView.turns");
  const format = useFormatter();
  const duration = useFormatDuration();
  const now = useNow(turns.some((turn) => turn.ended_at === null));
  const list = useRef<HTMLOListElement>(null);
  const selected = useRef<HTMLButtonElement>(null);
  // A picked turn may sit outside the list's scroll window. Only the list scrolls: scrollIntoView
  // would also move the page while someone reads the waterfall below.
  useEffect(() => {
    const [box, row] = [list.current, selected.current];
    if (!box || !row) return;
    if (row.offsetTop < box.scrollTop || row.offsetTop + row.offsetHeight > box.scrollTop + box.clientHeight) {
      box.scrollTop = row.offsetTop - (box.clientHeight - row.offsetHeight) / 2;
    }
  }, [value]);
  const durations = new Map(turns.map((turn) => [turn.turn_id, Math.max(0, (turn.ended_at ? Date.parse(turn.ended_at) : now) - Date.parse(turn.started_at))]));
  const longest = Math.max(...durations.values());

  // One grid for all rows (subgrid), so the columns line up whatever the start times' widths.
  return (
    <ol
      ref={list}
      aria-label={t("turns")}
      className="relative grid max-h-48 grid-cols-[auto_minmax(0,1fr)_3rem_4.5rem] content-start gap-x-2 overflow-y-auto rounded-2xl border border-border bg-muted/20 p-1 sm:grid-cols-[auto_minmax(0,1fr)_10rem_4.5rem] sm:gap-x-3"
    >
      {[...turns].reverse().map((turn) => {
        const ms = durations.get(turn.turn_id)!;
        const current = turn.turn_id === value;
        const started = new Date(turn.started_at);
        return (
          <li key={turn.turn_id} className="col-span-full grid grid-cols-subgrid">
            <button
              ref={current ? selected : undefined}
              type="button"
              aria-current={current ? "true" : undefined}
              onClick={() => onChange(turn.turn_id)}
              className={cn(
                "col-span-full grid grid-cols-subgrid items-center rounded-md px-2 py-1 text-left text-xs hover:bg-accent/60",
                current && "bg-accent",
              )}
            >
              <time dateTime={turn.started_at} title={format.dateTime(started, { dateStyle: "medium", timeStyle: "medium" })} className="tabular-nums text-muted-foreground">
                {format.dateTime(started, { month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" })}
              </time>
              <span className={cn("truncate", current && "font-medium")} title={turn.prompt_preview}>
                {turn.prompt_preview}
              </span>
              <span className="relative block h-2 rounded-sm bg-muted/50">
                <span
                  className={cn("absolute inset-y-0 left-0 min-w-[2px] rounded-sm", STATUS_BAR_CLASS[turn.status] ?? "bg-sky-500 dark:bg-sky-400", turn.status === "running" && "animate-pulse")}
                  style={{ width: `${longest > 0 ? (ms / longest) * 100 : 0}%` }}
                />
              </span>
              <span className="whitespace-nowrap text-right tabular-nums text-muted-foreground">
                {turn.status === "ok" ? null : <span className="sr-only">{t(`statuses.${turn.status}`)} </span>}
                {duration(ms)}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function Timeline({ turn, spans, server, token, sessionId, onOpenRole }: { turn: TurnSummary; spans: Span[]; server: string; token: string; sessionId: string; onOpenRole: (role: DebugRole) => void }) {
  const t = useTranslations("debugView.turns");
  const [open, setOpen] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const now = useNow(turn.ended_at === null);
  const turnStart = Date.parse(turn.started_at);
  const turnEnd = Math.max(turnStart, turn.ended_at ? Date.parse(turn.ended_at) : now);
  const rows = timelineRows(spans, turnEnd);
  const scale = (ms: number) => (turnEnd > turnStart ? (ms / (turnEnd - turnStart)) * 100 : 0);
  const toggleCollapsed = (spanId: string) =>
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (!next.delete(spanId)) next.add(spanId);
      return next;
    });

  return (
    <>
      <Summary summary={summarizeTurn(rows, turnStart, turnEnd)} />
      <ol className="flex flex-col rounded-2xl border border-border bg-muted/20 p-2">
        {waterfallLines(rows, collapsed).map((line) => {
          const id = line.chain[0].span.span_id;
          const tailId = line.chain[line.chain.length - 1].span.span_id;
          const expanded = line.hasChildren && !collapsed.has(tailId);
          return (
            <li key={id} className="min-w-0">
              <div className="flex rounded-md px-1.5 hover:bg-accent/60">
                <TreeGuides line={line} />
                <span className="relative w-3 shrink-0">
                  {line.hasChildren ? (
                    <button
                      type="button"
                      aria-expanded={expanded}
                      aria-label={t(expanded ? "collapse" : "expand")}
                      onClick={() => toggleCollapsed(tailId)}
                      className="absolute -left-0.5 top-1 flex h-4 w-4 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground"
                    >
                      <ChevronRight className={cn("h-3 w-3 transition-transform", expanded && "rotate-90")} />
                    </button>
                  ) : null}
                  {expanded ? <span className="absolute bottom-0 left-1/2 top-[1.125rem] border-l border-border" /> : null}
                </span>
                {/* The whole line opens the details for the mouse; the label is its keyboard-reachable button. */}
                <div
                  onClick={() => setOpen(open === id ? null : id)}
                  style={{ "--indent": `${line.depth * 0.75}rem` } as CSSProperties}
                  className="grid min-w-0 flex-1 cursor-pointer grid-cols-1 gap-1 py-1 pl-1 sm:grid-cols-[minmax(0,calc(15rem_-_var(--indent)))_minmax(0,1fr)] sm:items-center sm:gap-3"
                >
                  <LineLabel line={line} open={open === id} />
                  <span className="relative block h-3 w-full rounded-sm bg-muted/50">
                    {line.chain.map((row) => (
                      <SpanBar key={row.span.span_id} row={row} left={scale(row.start - turnStart)} width={scale(row.end - row.start)} />
                    ))}
                  </span>
                </div>
              </div>
              {open === id
                ? line.chain.map((row) => <SpanDetail key={row.span.span_id} row={row} turnStart={turnStart} server={server} token={token} sessionId={sessionId} onOpenRole={onOpenRole} />)
                : null}
            </li>
          );
        })}
      </ol>
    </>
  );
}

/** Rails of the ancestors that continue below, then this line's elbow; the elbow meets the first text line's middle. */
function TreeGuides({ line }: { line: WaterfallLine }) {
  if (line.depth === 0) return null;
  return (
    <>
      {line.rails.map((rail, index) => (
        <span key={index} className="relative w-3 shrink-0">
          {rail ? <span className="absolute inset-y-0 left-1/2 border-l border-border" /> : null}
        </span>
      ))}
      <span className="relative w-3 shrink-0">
        <span className="absolute left-1/2 top-0 h-3 w-1/2 rounded-bl-sm border-b border-l border-border" />
        {line.last ? null : <span className="absolute inset-y-0 left-1/2 border-l border-border" />}
      </span>
    </>
  );
}

function Summary({ summary }: { summary: TimeBreakdown }) {
  const t = useTranslations("debugView.turns");
  const duration = useFormatDuration();
  const format = useFormatter();
  const shares = TIME_CATEGORIES.filter((category) => summary.byCategory[category] > 0);
  const share = (ms: number) => (summary.wallMs > 0 ? ms / summary.wallMs : 0);

  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-border bg-background/88 p-4 shadow-sm">
      <div className="flex flex-wrap gap-x-8 gap-y-3">
        <Stat label={t("wall")} value={<span className="tabular-nums">{duration(summary.wallMs)}</span>} />
        <Stat label={t("system")} value={<span className="tabular-nums">{duration(summary.systemMs)}</span>} />
        <Stat label={t("categories.userWait")} value={<span className="tabular-nums">{duration(summary.userWaitMs)}</span>} />
      </div>
      <div className="flex h-3 w-full overflow-hidden rounded-sm" role="img" aria-label={t("breakdown")}>
        {shares.map((category) => (
          <span key={category} title={t(`categories.${category}`)} className={CATEGORY_CLASS[category]} style={{ width: `${share(summary.byCategory[category]) * 100}%`, ...(category === "userWait" ? HATCH : {}) }} />
        ))}
      </div>
      <ul className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2 lg:grid-cols-3">
        {shares.map((category) => (
          <li key={category} className="flex min-w-0 items-center gap-2">
            <span className={cn("h-2.5 w-2.5 shrink-0 rounded-sm", CATEGORY_CLASS[category])} style={category === "userWait" ? HATCH : undefined} />
            <span className="truncate">{t(`categories.${category}`)}</span>
            <span className="ml-auto shrink-0 tabular-nums text-muted-foreground">
              {duration(summary.byCategory[category])} · {format.number(share(summary.byCategory[category]), { style: "percent", maximumFractionDigits: 0 })}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** What a span did, from the attr that says most. */
function spanText({ kind, name, attrs }: Span): { text: string; mono: boolean } {
  const attr = (key: string) => (typeof attrs[key] === "string" && attrs[key] !== "" ? (attrs[key] as string) : null);
  switch (kind) {
    case "exec":
      return { text: name === "exec" ? (attr("command") ?? name) : [name, attr("tool")].filter(Boolean).join(" "), mono: true };
    case "file":
      return { text: [name, attr("path")].filter(Boolean).join(" "), mono: true };
    // build wait, profile sync, activate: which skill it was for.
    case "skill":
      return { text: [name, attr("skill")].filter(Boolean).join(" · "), mono: false };
    // Its name is the check's type and its subject repeats the call or domain next to it.
    case "sentinel":
      return { text: kind, mono: false };
    default:
      return { text: name, mono: false };
  }
}

/** The facts of a line's spans, in chain order. */
function useLineFacts(): (chain: TimelineRow[]) => Fact[] {
  const t = useTranslations("debugView.turns.facts");
  const rowFacts = ({ span }: TimelineRow, chain: TimelineRow[]) => {
    const { attrs } = span;
    const facts: Fact[] = [];
    if (typeof attrs.verdict === "string") facts.push({ text: attrs.verdict, tone: VERDICT_TONE[attrs.verdict] ?? "muted" });
    // A sentinel's `deny` in the same line already says it.
    if (attrs.denied === true && !chain.some((row) => row.span.attrs.verdict === "deny")) facts.push({ text: t("denied"), tone: "bad" });
    if (attrs.allowed === false) facts.push({ text: t("blocked"), tone: "bad" });
    if (typeof attrs.exit_code === "number" && attrs.exit_code !== 0) facts.push({ text: t("exitCode", { code: attrs.exit_code }), tone: "bad" });
    return facts;
  };
  return (chain) => chain.flatMap((row) => rowFacts(row, chain));
}

function useFormatRate(): (rate: number) => string {
  const t = useTranslations("debugView.turns.facts");
  const format = useFormatter();
  return (rate) => t("rate", { rate: format.number(rate, { maximumFractionDigits: 0 }) });
}

/** The line's spans, and the output of its LLM requests: too long for the row next to a long duration. */
function useLineTitle(): (chain: TimelineRow[]) => string {
  const t = useTranslations("debugView.turns.facts");
  const format = useFormatter();
  const formatRate = useFormatRate();
  return (chain) =>
    [
      chain.map(({ span }) => (span.name === span.kind ? span.kind : `${span.kind} · ${span.name}`)).join(" › "),
      ...chain.flatMap(({ span: { llm }, start, end }) => {
        if (!llm || llm.output_tokens === 0) return [];
        const rate = outputRate(llm, start, end);
        const tokens = t("output", { tokens: format.number(llm.output_tokens) });
        return [rate === null ? tokens : `${tokens} · ${formatRate(rate)}`];
      }),
    ].join("\n");
}

/**
 * Icon, text and facts of a line. A merged chain is named by its first span that is not a gate: a
 * gate's name is its tool's, so the sentinel call below it says more. The duration is the chain head's.
 */
function LineLabel({ line, open }: { line: WaterfallLine; open: boolean }) {
  const duration = useFormatDuration();
  const lineFacts = useLineFacts();
  const lineTitle = useLineTitle();
  const head = line.chain[0];
  const named = line.chain.find((row) => row.span.kind !== "gate") ?? head;
  const Icon = KIND_ICON[named.span.kind] ?? Circle;
  const { text, mono } = spanText(named.span);
  return (
    <button
      type="button"
      aria-expanded={open}
      title={lineTitle(line.chain)}
      className="flex w-full min-w-0 items-center gap-1.5 text-left text-xs"
    >
      <span role="img" aria-label={named.span.kind} className="shrink-0">
        <Icon aria-hidden className={cn("h-3.5 w-3.5", CATEGORY_TEXT[spanCategory(named.span)])} />
      </span>
      <span className={cn("min-w-0 truncate", mono && "font-mono")}>{text}</span>
      {lineFacts(line.chain).map((fact, index) => (
        <span key={index} className={cn("shrink-0", FACT_CLASS[fact.tone])}>
          {fact.text}
        </span>
      ))}
      {line.chain.some(({ span }) => span.status === "running") ? <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" /> : null}
      {/* Wide enough for durations up to "99 min 59 s" (the formatter has no hour unit), so they never push into the bar column. */}
      <span className="ml-auto w-[4.5rem] shrink-0 whitespace-nowrap text-right tabular-nums text-muted-foreground">{duration(head.end - head.start)}</span>
    </button>
  );
}

/** Positioned in % of the turn; an LLM request shows its phases, an error or interruption overrides every color. */
function SpanBar({ row, left, width }: { row: TimelineRow; left: number; width: number }) {
  const { span } = row;
  const statusClass = STATUS_BAR_CLASS[span.status];
  const segments = span.llm && !statusClass ? llmSegments(span.llm, row.start, row.end) : null;
  const category = spanCategory(span);
  return (
    <span
      className={cn("absolute inset-y-0 flex min-w-[2px] overflow-hidden rounded-sm", statusClass ?? (segments ? null : CATEGORY_CLASS[category]), span.status === "running" && "animate-pulse")}
      style={{ left: `${left}%`, width: `${width}%`, ...(category === "userWait" ? HATCH : {}) }}
    >
      {segments?.map((segment) => (
        <span key={segment.start} className={CATEGORY_CLASS[segment.category]} style={{ width: `${((segment.end - segment.start) / (row.end - row.start)) * 100}%` }} />
      ))}
    </span>
  );
}

const LLM_PHASES = ["llmWaiting", "llmThinking", "llmOutput"] as const;

function SpanDetail({ row, turnStart, server, token, sessionId, onOpenRole }: { row: TimelineRow; turnStart: number; server: string; token: string; sessionId: string; onOpenRole: (role: DebugRole) => void }) {
  const t = useTranslations("debugView.turns");
  const tRoles = useTranslations("debugView.roles");
  const tUsage = useTranslations("debugView.usage");
  const format = useFormatter();
  const formatCost = useFormatCost();
  const duration = useFormatDuration();
  const formatRate = useFormatRate();
  const { span } = row;
  const llm = span.llm;
  const count = (value: number | null) => (value === null ? "–" : format.number(value));
  // The role tab shows only the role's latest request, so the link appears only when this is it.
  const loadContext = useCallback(() => fetchLlmContext(server, token, sessionId, llm!.role), [server, token, sessionId, llm]);
  const context = useKeyedFetch(llm ? llm.request_id : null, loadContext);
  const isLatest = !!llm && !!context && "value" in context && context.value?.request_id === llm.request_id;
  const phases = llm ? llmSegments(llm, row.start, row.end) : [];
  const rate = llm ? outputRate(llm, row.start, row.end) : null;
  const phaseMs = (category: TimeCategory) => phases.filter((phase) => phase.category === category).reduce((sum, phase) => sum + phase.end - phase.start, 0);

  return (
    <div className="mx-1.5 mb-2 mt-1 flex flex-wrap gap-x-8 gap-y-3 rounded-xl border border-border bg-background p-3">
      <Stat label={t("detail.kind")} value={<span className="font-mono">{span.kind}</span>} />
      <Stat label={t("detail.status")} value={t(`statuses.${span.status}`)} />
      <Stat label={t("detail.start")} value={<span className="tabular-nums" title={format.dateTime(new Date(row.start), { dateStyle: "medium", timeStyle: "medium" })}>{t("offset", { value: duration(row.start - turnStart) })}</span>} />
      <Stat label={t("detail.duration")} value={<span className="tabular-nums">{duration(row.end - row.start)}</span>} />
      {Object.entries(span.attrs).map(([key, value]) => (
        <Stat key={key} label={key} value={<span className="break-all font-mono">{String(value)}</span>} />
      ))}
      {llm ? (
        <div className="flex basis-full flex-wrap gap-x-8 gap-y-3 border-t border-border/60 pt-3">
          <Stat label={t("detail.model")} value={<span className="font-mono">{llm.model_name ?? "–"}</span>} />
          {LLM_PHASES.filter((phase) => phaseMs(phase) > 0).map((phase) => (
            <Stat key={phase} label={t(`detail.${phase}`)} value={<span className="tabular-nums">{duration(phaseMs(phase))}</span>} />
          ))}
          <Stat label={t("detail.input")} value={<span className="tabular-nums">{count(llm.input_tokens)}</span>} />
          <Stat label={t("detail.output")} value={<span className="tabular-nums">{count(llm.output_tokens)}</span>} />
          {rate === null ? null : <Stat label={t("detail.outputRate")} value={<span className="tabular-nums">{formatRate(rate)}</span>} />}
          <Stat label={t("detail.cacheRead")} value={<span className="tabular-nums">{count(llm.cache_read_tokens)}</span>} />
          <Stat label={t("detail.cacheWrite")} value={<span className="tabular-nums">{count(llm.cache_write_tokens)}</span>} />
          <Stat label={t("detail.cost")} value={llm.cost ? (formatCost(llm.cost) ?? tUsage("unpriced")) : "–"} />
          {isLatest ? (
            <button type="button" onClick={() => onOpenRole(llm.role)} className="self-end text-sm underline underline-offset-2">
              {t("detail.openRole", { role: tRoles(llm.role) })}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
