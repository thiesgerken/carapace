"use client";

import { useCallback, useState, type ReactNode } from "react";
import { Braces, CircleSlash, CircleX, Loader2 } from "lucide-react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { useFormatCost } from "@/components/memory-ui";
import { MarkdownContent } from "@/components/markdown-content";
import { pillClassName } from "@/components/prompt-preview-view";
import { Stat } from "@/components/debug-stat";
import { SessionHeader } from "@/components/session-header";
import { CATEGORY_CLASS, TurnTimelineView } from "@/components/turn-timeline-view";
import { useDebounced } from "@/hooks/use-debounced";
import { useKeyedFetch } from "@/hooks/use-keyed-fetch";
import { useWebSocket, useWebSocketTicket } from "@/hooks/use-websocket";
import { fetchLlmContext, fetchLlmRequests, fetchTurns, wsUrl } from "@/lib/api";
import { formatUsd } from "@/lib/memory";
import { fencedCodeBlock } from "@/lib/sandbox-read";
import {
  DEBUG_ROLES,
  type DebugRole,
  type DebugTab,
  type LlmContext,
  type LlmContextStatus,
  type LlmMessage,
  type LlmRequestCost,
  type LlmRequestUsage,
  type LlmPart,
  type LlmRequestRecord,
  type ServerMessage,
  type TurnSummary,
} from "@/lib/types";
import { cacheHitRate, costShape, isEmptyColumn } from "@/lib/request-table";
import { groupRequestsByTurn, llmSegments } from "@/lib/turn-timeline";
import { cn } from "@/lib/utils";

const STATUS_CLASS: Record<LlmContextStatus, string> = {
  running: "border-sky-500/40 bg-sky-500/10 text-sky-800 dark:text-sky-300",
  completed: "border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300",
  failed: "border-destructive/40 bg-destructive/10 text-destructive",
  interrupted: "border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300",
};

const TIMELINE_REFETCH_DEBOUNCE_MS = 250;
const TIMELINE_REFETCH_MAX_WAIT_MS = 1000;

type Notification = { requestId: string; status: LlmContextStatus };
type RoleFetch<T> = (server: string, token: string, sessionId: string, role: DebugRole) => Promise<T>;

/** What *fetchRole* returns for *role*, refetched whenever *revision* (the role's latest notification) changes. */
function useRoleFetch<T>(fetchRole: RoleFetch<T>, server: string, token: string, sessionId: string, role: DebugRole, revision: string) {
  const load = useCallback(() => fetchRole(server, token, sessionId, role), [fetchRole, server, token, sessionId, role]);
  const outcome = useKeyedFetch(`${role}:${revision}`, load);
  // A result for another role keeps showing while this one loads, so it is dropped here.
  return outcome?.key.startsWith(`${role}:`) ? outcome : null;
}

/** The turn timeline and the latest LLM context of every agent role in a session, updated live over the session WebSocket. */
export function DebugView({
  server,
  token,
  sessionId,
  title,
  initialTab = "timeline",
  initialTurn = null,
}: {
  server: string;
  token: string;
  sessionId: string;
  title: string | null | undefined;
  initialTab?: DebugTab;
  initialTurn?: string | null;
}) {
  const t = useTranslations("debugView");
  const [tab, setTab] = useState<DebugTab>(initialTab);
  // Kept here so the picked turn survives a detour through a role tab.
  const [pickedTurn, setPickedTurn] = useState(initialTurn);
  const [notifications, setNotifications] = useState<Partial<Record<DebugRole, Notification>>>({});
  const [timelineEvents, setTimelineEvents] = useState(0);

  const onMessage = useCallback((msg: ServerMessage) => {
    // Spans start and end; LLM activity also moves a running request through its phases.
    if (msg.type === "span" || msg.type === "llm_activity") setTimelineEvents((count) => count + 1);
    if (msg.type !== "llm_context") return;
    setNotifications((current) => ({ ...current, [msg.role]: { requestId: msg.request_id, status: msg.status } }));
  }, []);
  const ticket = useWebSocketTicket(server, token);
  const { status } = useWebSocket(ticket ? wsUrl(server, sessionId, token, undefined, ticket, true) : null, onMessage);
  // Notifications sent while the socket was down are lost, so every (re)connect refetches too.
  const connected = status === "connected";
  // A busy turn sends bursts of notifications: one refetch per burst, but at least one per second while it lasts.
  const timelineRevision = useDebounced(`${connected}:${timelineEvents}`, TIMELINE_REFETCH_DEBOUNCE_MS, TIMELINE_REFETCH_MAX_WAIT_MS);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <SessionHeader sessionId={sessionId} title={title} view="debug" />
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
        <p className="text-sm text-muted-foreground">{t(tab === "timeline" ? "turns.hint" : "hint")}</p>

        {/* Two groups: the turns, then one request tab per role. On a phone the role group takes its own line. */}
        <div role="radiogroup" aria-label={t("tab")} className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <button type="button" role="radio" aria-checked={tab === "timeline"} onClick={() => setTab("timeline")} className={pillClassName(tab === "timeline")}>
            {t("turns.tab")}
          </button>
          <span aria-hidden className="hidden h-5 w-px bg-border sm:block" />
          <div role="group" aria-labelledby="debug-request-tabs" className="flex basis-full flex-wrap items-center gap-1.5 sm:basis-auto">
            <span id="debug-request-tabs" className="mr-0.5 text-xs text-muted-foreground">
              {t("requestTabs")}
            </span>
            {DEBUG_ROLES.map((role) => (
              <button key={role} type="button" role="radio" aria-checked={role === tab} onClick={() => setTab(role)} className={cn(pillClassName(role === tab), "inline-flex items-center gap-1.5")}>
                {t(`roles.${role}`)}
                {notifications[role]?.status === "running" ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              </button>
            ))}
          </div>
        </div>

        {tab === "timeline" ? (
          <TurnTimelineView
            server={server}
            token={token}
            sessionId={sessionId}
            pickedTurn={pickedTurn}
            onPickTurn={setPickedTurn}
            revision={timelineRevision}
            onOpenRole={setTab}
          />
        ) : (
          <RoleDebug
            key={tab}
            server={server}
            token={token}
            sessionId={sessionId}
            role={tab}
            revision={`${connected}:${notifications[tab] ? `${notifications[tab].requestId}:${notifications[tab].status}` : ""}`}
            onOpenTurn={(turnId) => {
              setPickedTurn(turnId);
              setTab("timeline");
            }}
          />
        )}
      </div>
      </div>
    </div>
  );
}

/** A role's request table and its latest context; *revision* changes on the role's notifications. */
function RoleDebug({
  server,
  token,
  sessionId,
  role,
  revision,
  onOpenTurn,
}: {
  server: string;
  token: string;
  sessionId: string;
  role: DebugRole;
  revision: string;
  /** Null follows the newest turn. */
  onOpenTurn: (turnId: string | null) => void;
}) {
  const t = useTranslations("debugView");
  // The role's context and timeline from an older notification keep showing while the next ones load.
  const current = useRoleFetch(fetchLlmContext, server, token, sessionId, role, revision);
  const shown = current && "value" in current ? current.value : undefined;
  const timeline = useRoleFetch(fetchLlmRequests, server, token, sessionId, role, revision);
  // Only the group headers need the turns, so a failed or pending list just leaves them without a prompt.
  const loadTurns = useCallback(() => fetchTurns(server, token, sessionId), [server, token, sessionId]);
  const turns = useKeyedFetch(revision, loadTurns);
  const turnList = turns && "value" in turns ? turns.value : [];

  return (
    <>
      {timeline && "error" in timeline ? (
        <p className="text-sm text-destructive">{t("timeline.loadError", { error: timeline.error })}</p>
      ) : timeline?.value.length ? (
        <RequestTimeline
          records={timeline.value}
          turns={turnList}
          contextRequestId={shown?.request_id}
          // Like the turn picker: opening the newest turn keeps following new ones.
          onOpenTurn={(turnId) => onOpenTurn(turnId === turnList.at(-1)?.turn_id ? null : turnId)}
        />
      ) : null}

      {current && "error" in current ? (
        <p className="text-sm text-destructive">{t("loadError", { error: current.error })}</p>
      ) : shown === undefined ? (
        <Loader2 className="mx-auto mt-8 h-5 w-5 animate-spin text-muted-foreground" />
      ) : shown === null ? (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      ) : (
        <div id={CONTEXT_ANCHOR} className="scroll-mt-4">
          <LlmContextView context={shown} />
        </div>
      )}
    </>
  );
}

export function LlmContextView({ context }: { context: LlmContext }) {
  const t = useTranslations("debugView");
  const format = useFormatter();

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start gap-x-8 gap-y-3 rounded-2xl border border-border bg-background/88 p-4 shadow-sm">
        <Stat label={t("status")} value={<StatusBadge status={context.status} />} />
        <Stat label={t("model")} value={<span className="font-mono">{context.model_name}</span>} />
        <Stat label={t("started")} value={format.dateTime(new Date(context.started_at), { dateStyle: "medium", timeStyle: "medium" })} />
        {context.compaction_target ? (
          <Stat label={t("compacted")} value={t(`compactionTargets.${context.compaction_target}`)} />
        ) : null}
        {context.response?.usage ? <UsageStats usage={context.response.usage} cost={context.cost} /> : null}
      </div>

      {context.error ? (
        <pre className="whitespace-pre-wrap break-words rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{context.error}</pre>
      ) : null}

      <Collapsible title={t("instructions")} open>
        {context.instructions.map((part, index) => (
          <Card key={index} label={part.name ?? t(part.dynamic ? "dynamic" : "static")}>
            <MarkdownContent content={part.content} />
          </Card>
        ))}
      </Collapsible>

      <Collapsible title={t("tools", { count: context.tool_definitions.length })}>
        {context.tool_definitions.map((tool) => (
          <Card key={tool.name} label={tool.name}>
            {tool.description ? <MarkdownContent content={tool.description} /> : null}
            <Json value={tool.parameters_json_schema} />
          </Card>
        ))}
      </Collapsible>

      <Collapsible title={t("messages", { count: context.messages.length })} open>
        {context.messages.map((message, index) => (
          <MessageCard key={index} message={message} label={t(message.kind === "request" ? "request" : "response")} />
        ))}
      </Collapsible>

      {context.response ? (
        <MessageCard message={context.response} label={t("response")} highlight />
      ) : context.status === "running" ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("waiting")}
        </p>
      ) : null}
    </div>
  );
}

const CONTEXT_ANCHOR = "llm-context";

type TimelineColumn = { key: string; numeric?: boolean; cell: (record: LlmRequestRecord) => ReactNode };

/**
 * One row per recorded request of the role, newest first, so requests compare side by side without
 * their contexts. Rows are grouped by turn, which shows per-turn patterns such as a turn's first
 * request missing the cache. The table stresses exceptions, not the norm: a completed request has
 * no status marker, a cache miss stands out, and count columns that are empty in every row go.
 */
function RequestTimeline({
  records,
  turns,
  contextRequestId,
  onOpenTurn,
}: {
  records: LlmRequestRecord[];
  turns: TurnSummary[];
  contextRequestId: string | undefined;
  onOpenTurn: (turnId: string) => void;
}) {
  const t = useTranslations("debugView.timeline");
  const format = useFormatter();
  // Compact counts compare at a glance; the exact one is in the tooltip. Null is unknown: the record predates it.
  const count = (value: number | null) =>
    value === null ? <span className="text-muted-foreground">–</span> : <span title={format.number(value)}>{format.number(value, { notation: "compact", maximumFractionDigits: 1 })}</span>;
  const countColumn = (key: string, value: (record: LlmRequestRecord) => number | null): TimelineColumn[] =>
    isEmptyColumn(records, value) ? [] : [{ key, numeric: true, cell: (r) => count(value(r)) }];
  const columns: TimelineColumn[] = [
    { key: "time", cell: (r) => <Time record={r} linked={r.request_id !== null && r.request_id === contextRequestId} /> },
    { key: "duration", cell: (r) => <RequestDuration record={r} /> },
    { key: "input", numeric: true, cell: (r) => count(r.input_tokens) },
    ...(records.every((r) => r.cache_read_tokens === null) ? [] : [{ key: "cacheHitRate", cell: (r: LlmRequestRecord) => <CacheMeter record={r} /> }]),
    ...countColumn("cacheRead", (r) => r.cache_read_tokens),
    ...countColumn("cacheWrite", (r) => r.cache_write_tokens),
    { key: "output", numeric: true, cell: (r) => count(r.output_tokens) },
    ...countColumn("reasoning", (r) => r.reasoning_tokens),
    { key: "cost", numeric: true, cell: (r) => <CostCell cost={r.cost} /> },
    { key: "model", cell: (r) => <span className="font-mono text-muted-foreground">{r.model_name ?? "–"}</span> },
  ];

  return (
    <Collapsible title={t("title", { count: records.length })} open>
      <div className="overflow-x-auto">
        <table className="w-full whitespace-nowrap text-xs">
          <thead>
            <tr className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {columns.map((column) => (
                <th key={column.key} scope="col" className={cn("px-2 py-1.5 font-medium", column.numeric ? "text-right" : "text-left")}>{t(`columns.${column.key}`)}</th>
              ))}
            </tr>
          </thead>
          {groupRequestsByTurn(records).map((group) => (
            <tbody key={group.turnId ?? ""} className="tabular-nums">
              <tr className="border-t border-border">
                <th scope="rowgroup" colSpan={columns.length} className="bg-muted/40 px-2 py-1.5 text-left font-normal">
                  <TurnHeader turnId={group.turnId} turn={turns.find((turn) => turn.turn_id === group.turnId)} onOpenTurn={onOpenTurn} />
                </th>
              </tr>
              {group.records.map((record, index) => (
                <tr key={record.request_id ?? index} className={cn("border-t border-border/60", record.request_id !== null && record.request_id === contextRequestId && "bg-sky-500/10")}>
                  {columns.map((column) => (
                    <td key={column.key} className={cn("px-2 py-1.5", column.numeric && "text-right")}>{column.cell(record)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </Collapsible>
  );
}

/** The main column after the time: how long the request took, with its phases in the waterfall's colors. */
function RequestDuration({ record }: { record: LlmRequestRecord }) {
  const t = useTranslations("debugView.timeline");
  const format = useFormatter();
  if (!record.started_at || !record.completed_at) return <span className="text-muted-foreground">–</span>;
  const [start, end] = [Date.parse(record.started_at), Date.parse(record.completed_at)];
  return (
    <span className="flex items-center gap-2">
      <span className="w-12 text-right font-medium text-foreground">{t("seconds", { seconds: format.number((end - start) / 1000, { maximumFractionDigits: 1 }) })}</span>
      <PhaseBar phases={record} start={start} end={end} className="w-16" />
    </span>
  );
}

/** An LLM request's phases (first token, thinking, output) as a thin bar. */
function PhaseBar({ phases, start, end, className }: { phases: LlmRequestRecord; start: number; end: number; className?: string }) {
  const segments = end > start ? llmSegments(phases, start, end) : [];
  return (
    <span aria-hidden className={cn("flex h-1.5 overflow-hidden rounded-full bg-muted", className)}>
      {segments.map((segment) => (
        <span key={segment.start} className={CATEGORY_CLASS[segment.category]} style={{ width: `${((segment.end - segment.start) / (end - start)) * 100}%` }} />
      ))}
    </span>
  );
}

/** Hits are the norm and stay quiet; a miss, the thing to notice, gets the accent. */
function CacheMeter({ record }: { record: LlmRequestRecord }) {
  const t = useTranslations("debugView.timeline");
  const format = useFormatter();
  const rate = cacheHitRate(record);
  if (rate === null) return <span className="text-muted-foreground">–</span>;
  const miss = rate === 0;
  return (
    <span className="flex items-center gap-1.5" title={miss ? t("cacheMiss") : undefined}>
      <span aria-hidden className={cn("h-1.5 w-10 overflow-hidden rounded-full", miss ? "bg-amber-500/30" : "bg-muted")}>
        <span className="block h-full bg-muted-foreground/45" style={{ width: `${rate * 100}%` }} />
      </span>
      <span className={cn("w-9 text-right", miss ? "font-medium text-amber-700 dark:text-amber-300" : "text-muted-foreground")}>
        {format.number(rate, { style: "percent", maximumFractionDigits: 0 })}
      </span>
    </span>
  );
}

/** Actual and equivalent cost in one cell: a subscription request shows its equivalent, marked as such. */
function CostCell({ cost }: { cost: LlmRequestCost | null }) {
  const t = useTranslations("debugView.timeline");
  const locale = useLocale();
  const usd = (value: string | null) => formatUsd(value ?? 0, locale);
  switch (costShape(cost)) {
    case "none":
      return <span className="text-muted-foreground">–</span>;
    case "actual":
      return usd(cost!.cost_usd);
    case "subscription":
      return (
        <span className="text-muted-foreground" title={t("subscription")}>
          ≈ {usd(cost!.equivalent_cost_usd)}
        </span>
      );
    case "both":
      return (
        <span>
          {usd(cost!.cost_usd)} <span className="text-muted-foreground">(≈ {usd(cost!.equivalent_cost_usd)})</span>
        </span>
      );
  }
}

/** A turn's start and prompt, linking to it in the Turns tab; a turn missing from the turn list (no timing recorded) shows its id only. */
function TurnHeader({ turnId, turn, onOpenTurn }: { turnId: string | null; turn: TurnSummary | undefined; onOpenTurn: (turnId: string) => void }) {
  const t = useTranslations("debugView.timeline");
  const format = useFormatter();
  if (turnId === null) return <span className="sticky left-2 text-muted-foreground">{t("outsideTurn")}</span>;
  if (turn === undefined) return <span className="sticky left-2 font-mono text-muted-foreground">{turnId}</span>;
  return (
    // Sticky, so the header stays in view while the wide table scrolls sideways (on a phone).
    <span className="sticky left-2 flex w-fit min-w-0 items-center gap-2">
      <span className="text-muted-foreground">{format.dateTime(new Date(turn.started_at), { month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" })}</span>
      <span className="min-w-0 max-w-[8rem] truncate font-medium sm:max-w-[32rem]">{turn.prompt_preview}</span>
      <button type="button" onClick={() => onOpenTurn(turnId)} className="underline underline-offset-2">
        {t("showTurn")}
      </button>
    </span>
  );
}

/** Day and time are enough to tell requests apart; the full timestamp is in the tooltip. The shown context's row links to it. */
function Time({ record, linked }: { record: LlmRequestRecord; linked: boolean }) {
  const t = useTranslations("debugView.timeline");
  const format = useFormatter();
  const date = new Date(record.ts);
  const short = format.dateTime(date, { month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" });
  const full = format.dateTime(date, { dateStyle: "medium", timeStyle: "medium" });
  return (
    <span className="flex items-center gap-1.5">
      {linked ? (
        <a href={`#${CONTEXT_ANCHOR}`} title={`${full} · ${t("showContext")}`} className="underline underline-offset-2">{short}</a>
      ) : (
        <span title={full}>{short}</span>
      )}
      <StatusMark status={record.outcome} />
    </span>
  );
}

/** Completed is the norm and goes unmarked; the exceptions get a small icon. */
function StatusMark({ status }: { status: LlmContextStatus }) {
  const t = useTranslations("debugView.statuses");
  switch (status) {
    case "completed":
      return null;
    case "running":
      return <Loader2 role="img" aria-label={t(status)} className="h-3.5 w-3.5 animate-spin text-sky-600 dark:text-sky-400" />;
    case "failed":
      return <CircleX role="img" aria-label={t(status)} className="h-3.5 w-3.5 text-destructive" />;
    case "interrupted":
      return <CircleSlash role="img" aria-label={t(status)} className="h-3.5 w-3.5 text-muted-foreground" />;
  }
}

const AUDIO_TOKENS = ["input_audio_tokens", "output_audio_tokens", "cache_audio_read_tokens"] as const;

/** The response's usage as the provider reported it, and what it cost. */
function UsageStats({ usage, cost }: { usage: LlmRequestUsage; cost: LlmRequestCost | null }) {
  const t = useTranslations("debugView.usage");
  const format = useFormatter();
  const locale = useLocale();
  const formatCost = useFormatCost();
  const tokens = (value: number | undefined) => <span className="tabular-nums">{format.number(value ?? 0)}</span>;

  return (
    <div className="flex basis-full flex-wrap gap-x-8 gap-y-3 border-t border-border/60 pt-3">
      <Stat label={t("input")} value={tokens(usage.input_tokens)} />
      <Stat label={t("output")} value={tokens(usage.output_tokens)} />
      <Stat label={t("cacheRead")} value={tokens(usage.cache_read_tokens)} />
      <Stat label={t("cacheWrite")} value={tokens(usage.cache_write_tokens)} />
      {AUDIO_TOKENS.filter((key) => usage[key]).map((key) => (
        <Stat key={key} label={t(key)} value={tokens(usage[key])} />
      ))}
      {Object.entries(usage.details ?? {}).map(([key, value]) => (
        <Stat key={key} label={key} value={tokens(value)} />
      ))}
      {cost ? <Stat label={t("cost")} value={formatCost(cost) ?? t("unpriced")} /> : null}
      {cost?.provider_cost_usd ? <Stat label={t("providerCost")} value={formatUsd(cost.provider_cost_usd, locale)} /> : null}
    </div>
  );
}

function MessageCard({ message, label, highlight = false }: { message: LlmMessage; label: string; highlight?: boolean }) {
  const t = useTranslations("debugView");
  const [raw, setRaw] = useState(false);

  return (
    <section className={cn("rounded-xl border bg-background p-3", highlight ? "border-[#236b86]/50 dark:border-sky-400/40" : "border-border")}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{label}</span>
        <button type="button" aria-pressed={raw} onClick={() => setRaw(!raw)} className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground">
          <Braces className="h-3.5 w-3.5" />
          {raw ? t("showFormatted") : t("showRaw")}
        </button>
      </div>
      {raw ? (
        <Json value={message} />
      ) : (
        <div className="flex flex-col gap-2">
          {message.parts.map((part, index) => <PartCard key={index} part={part} />)}
        </div>
      )}
    </section>
  );
}

function PartCard({ part }: { part: LlmPart }) {
  const t = useTranslations("debugView.parts");
  switch (part.part_kind) {
    case "system-prompt":
      return <Card label={t("systemPrompt")}><Content value={part.content} markdown /></Card>;
    case "user-prompt":
      return <Card label={t("userPrompt")}><Content value={part.content} markdown /></Card>;
    case "text":
      return <Card label={t("text")}><Content value={part.content} markdown /></Card>;
    case "thinking":
      return <Card label={t("thinking")} muted><Content value={part.content} markdown /></Card>;
    case "tool-call":
      return <Card label={`${t("toolCall")} · ${part.tool_name}`} badge={part.tool_call_id}><Json value={parseArgs(part.args)} /></Card>;
    case "tool-return":
      return <Card label={`${t(part.outcome === "retried" ? "toolRetry" : "toolReturn")} · ${part.tool_name}`} badge={part.tool_call_id}><Content value={part.content} /></Card>;
    case "retry-feedback":
      return <Card label={t("retryFeedback")}><Content value={part.content} /></Card>;
    default:
      // Provider-specific parts (native tools, files, compaction) render as what they are.
      return <Card label={part.part_kind}><Json value={part} /></Card>;
  }
}

/** pydantic-ai keeps tool call args either as a dict or as the model's raw JSON string. */
function parseArgs(args: unknown): unknown {
  if (typeof args !== "string") return args;
  try {
    return JSON.parse(args);
  } catch {
    return args;
  }
}

/** Prose to and from the model renders as Markdown; tool output stays verbatim, Markdown would mangle it. */
function Content({ value, markdown = false }: { value: unknown; markdown?: boolean }) {
  if (typeof value !== "string") return <Json value={value} />;
  return markdown ? <MarkdownContent content={value} /> : <Verbatim>{value}</Verbatim>;
}

function Verbatim({ children }: { children: string }) {
  return <pre className="whitespace-pre-wrap break-words rounded-lg bg-muted/50 p-2 font-mono text-xs">{children}</pre>;
}

/** A string is tool call args the model sent as invalid JSON: shown as sent, not highlighted as JSON. */
function Json({ value }: { value: unknown }) {
  if (typeof value === "string") return <Verbatim>{value}</Verbatim>;
  return <MarkdownContent content={fencedCodeBlock("json", JSON.stringify(value, null, 2))} />;
}

function Card({ label, badge, muted = false, children }: { label: string; badge?: string; muted?: boolean; children: ReactNode }) {
  return (
    <div className={cn("min-w-0 rounded-lg border border-border/70 p-2.5 text-sm", muted && "bg-muted/30 text-muted-foreground")}>
      <div className="mb-1.5 flex min-w-0 items-center justify-between gap-2 text-xs font-medium">
        <span className="truncate">{label}</span>
        {badge ? <span className="truncate font-mono text-[11px] text-muted-foreground">{badge}</span> : null}
      </div>
      {children}
    </div>
  );
}

function Collapsible({ title, open = false, children }: { title: string; open?: boolean; children: ReactNode }) {
  return (
    <details open={open} className="group rounded-2xl border border-border bg-muted/20 p-3">
      <summary className="cursor-pointer text-sm font-medium">{title}</summary>
      <div className="mt-3 flex flex-col gap-2">{children}</div>
    </details>
  );
}

function StatusBadge({ status }: { status: LlmContextStatus }) {
  const t = useTranslations("debugView.statuses");
  return <span className={cn("inline-flex rounded-full border px-2 py-0.5 text-xs font-medium", STATUS_CLASS[status])}>{t(status)}</span>;
}
