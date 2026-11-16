"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { Loader2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { Stat } from "@/components/debug-stat";
import { useFormatCost } from "@/components/memory-ui";
import { useKeyedFetch } from "@/hooks/use-keyed-fetch";
import { fetchLlmContext, fetchTurns, fetchTurnTimeline } from "@/lib/api";
import { llmSegments, spanCategory, summarizeTurn, TIME_CATEGORIES, timelineRows, type TimeCategory, type TimelineRow, type TimeBreakdown } from "@/lib/turn-timeline";
import type { DebugRole, Span, SpanStatus, TurnSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const CATEGORY_CLASS: Record<TimeCategory, string> = {
  llmWaiting: "bg-sky-300 dark:bg-sky-800",
  llmThinking: "bg-violet-400 dark:bg-violet-500",
  llmOutput: "bg-sky-600 dark:bg-sky-400",
  sentinel: "bg-amber-500 dark:bg-amber-400",
  sandbox: "bg-emerald-500 dark:bg-emerald-400",
  skill: "bg-lime-500 dark:bg-lime-400",
  execFile: "bg-pink-500 dark:bg-pink-400",
  credential: "bg-teal-500 dark:bg-teal-400",
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

/** Ticks while *active*, so running spans grow to now. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

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
      <TurnPicker turns={turnList} value={turnId} onChange={(value) => onPickTurn(value === newest ? null : value)} />
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

function TurnPicker({ turns, value, onChange }: { turns: TurnSummary[]; value: string | null; onChange: (turnId: string) => void }) {
  const t = useTranslations("debugView.turns");
  const format = useFormatter();
  const duration = useFormatDuration();
  return (
    <label className="flex min-w-0 flex-col gap-1 text-xs font-medium text-muted-foreground">
      {t("turn")}
      <select value={value ?? ""} onChange={(event) => onChange(event.target.value)} className="w-full min-w-0 rounded-lg border border-border bg-background px-2 py-1.5 text-sm text-foreground">
        {[...turns].reverse().map((turn) => (
          <option key={turn.turn_id} value={turn.turn_id}>
            {[
              format.dateTime(new Date(turn.started_at), { month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" }),
              turn.prompt_preview,
              turn.ended_at ? duration(Date.parse(turn.ended_at) - Date.parse(turn.started_at)) : t("running"),
            ].join(" · ")}
          </option>
        ))}
      </select>
    </label>
  );
}

function Timeline({ turn, spans, server, token, sessionId, onOpenRole }: { turn: TurnSummary; spans: Span[]; server: string; token: string; sessionId: string; onOpenRole: (role: DebugRole) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const now = useNow(turn.ended_at === null);
  const turnStart = Date.parse(turn.started_at);
  const turnEnd = Math.max(turnStart, turn.ended_at ? Date.parse(turn.ended_at) : now);
  const rows = timelineRows(spans, turnEnd);
  const scale = (ms: number) => (turnEnd > turnStart ? (ms / (turnEnd - turnStart)) * 100 : 0);

  return (
    <>
      <Summary summary={summarizeTurn(rows, turnStart, turnEnd)} />
      <ol className="flex flex-col rounded-2xl border border-border bg-muted/20 p-2">
        {rows.map((row) => (
          <li key={row.span.span_id} className="min-w-0">
            <button
              type="button"
              aria-expanded={open === row.span.span_id}
              onClick={() => setOpen(open === row.span.span_id ? null : row.span.span_id)}
              className="grid w-full grid-cols-1 gap-1 rounded-md px-1.5 py-1 text-left hover:bg-accent/60 sm:grid-cols-[minmax(0,16rem)_minmax(0,1fr)] sm:items-center sm:gap-3"
            >
              <SpanLabel row={row} />
              <span className="relative block h-3 w-full rounded-sm bg-muted/50">
                <SpanBar row={row} left={scale(row.start - turnStart)} width={scale(row.end - row.start)} />
              </span>
            </button>
            {open === row.span.span_id ? <SpanDetail row={row} turnStart={turnStart} server={server} token={token} sessionId={sessionId} onOpenRole={onOpenRole} /> : null}
          </li>
        ))}
      </ol>
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

function SpanLabel({ row }: { row: TimelineRow }) {
  const duration = useFormatDuration();
  return (
    <span className="flex min-w-0 items-center gap-1.5 text-xs" style={{ paddingLeft: `${row.depth * 0.75}rem` }}>
      <span className="truncate" title={row.span.kind}>{row.span.name}</span>
      {row.span.status === "running" ? <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" /> : null}
      <span className="ml-auto shrink-0 tabular-nums text-muted-foreground">{duration(row.end - row.start)}</span>
    </span>
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
  const { span } = row;
  const llm = span.llm;
  const count = (value: number | null) => (value === null ? "–" : format.number(value));
  // The role tab shows only the role's latest request, so the link appears only when this is it.
  const loadContext = useCallback(() => fetchLlmContext(server, token, sessionId, llm!.role), [server, token, sessionId, llm]);
  const context = useKeyedFetch(llm ? llm.request_id : null, loadContext);
  const isLatest = !!llm && !!context && "value" in context && context.value?.request_id === llm.request_id;
  const phases = llm ? llmSegments(llm, row.start, row.end) : [];
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
