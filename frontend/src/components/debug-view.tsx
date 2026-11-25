"use client";

import { useCallback, useState, type ReactNode } from "react";
import {
  ArrowDownLeft,
  ArrowUpRight,
  Bot,
  Box,
  Braces,
  Brain,
  CircleSlash,
  CircleX,
  CornerDownLeft,
  Loader2,
  RotateCcw,
  ScrollText,
  User,
  Wrench,
  type LucideIcon,
} from "lucide-react";
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
  INPUT_SHAPE_KINDS,
  type DebugRole,
  type InputShape,
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
import { cacheHitRate, compactCount, costShape, isEmptyColumn, requestDurationMs } from "@/lib/request-table";
import { groupRequestsByTurn, llmSegments } from "@/lib/turn-timeline";
import { cn } from "@/lib/utils";

const STATUS_CLASS: Record<LlmContextStatus, string> = {
  running: "border-info/40 bg-info/10 text-info",
  completed: "border-success/40 bg-success/10 text-success",
  failed: "border-destructive/40 bg-destructive/10 text-destructive",
  interrupted: "border-warning/40 bg-warning/10 text-warning",
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
  onOpenTurn: (turnId: string) => void;
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
          onOpenTurn={onOpenTurn}
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
          <LlmContextView context={shown} record={timeline && "value" in timeline ? timeline.value.find((r) => r.request_id === shown.request_id) : undefined} />
        </div>
      )}
    </>
  );
}

/** The latest request of a role; *record* is its row in the request log, with phases and input shape, once it is recorded. */
export function LlmContextView({ context, record }: { context: LlmContext; record?: LlmRequestRecord }) {
  const t = useTranslations("debugView");
  const tTimeline = useTranslations("debugView.timeline");
  const format = useFormatter();
  const [start, end] = [Date.parse(context.started_at), context.completed_at ? Date.parse(context.completed_at) : null];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start gap-x-8 gap-y-3 rounded-2xl bg-surface p-4">
        {/* Completed is the norm; only the exceptions show a status. */}
        {context.status === "completed" ? null : <Stat label={t("status")} value={<StatusBadge status={context.status} />} />}
        <Stat label={t("model")} value={<span className="font-mono">{context.model_name}</span>} />
        <Stat label={t("started")} value={format.dateTime(new Date(context.started_at), { dateStyle: "medium", timeStyle: "medium" })} />
        {end === null ? null : (
          <Stat
            label={t("duration")}
            value={
              <span className="flex items-center gap-2">
                <span className="tabular-nums">{tTimeline("seconds", { seconds: format.number((end - start) / 1000, { maximumFractionDigits: 1 }) })}</span>
                {record ? <PhaseBar phases={record} start={start} end={end} className="w-24" /> : null}
              </span>
            }
          />
        )}
        {context.compaction_target ? (
          <Stat label={t("compacted")} value={t(`compactionTargets.${context.compaction_target}`)} />
        ) : null}
        {context.response?.usage ? <UsageStats usage={context.response.usage} cost={context.cost} /> : null}
        {record?.input_shape ? <InputShapeBar shape={record.input_shape} /> : null}
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
    value === null ? <span className="text-muted-foreground">–</span> : <span title={format.number(value)}>{compactCount(value, (n, maximumFractionDigits) => format.number(n, { maximumFractionDigits }))}</span>;
  const countColumn = (key: string, value: (record: LlmRequestRecord) => number | null): TimelineColumn[] =>
    isEmptyColumn(records, value) ? [] : [{ key, numeric: true, cell: (r) => count(value(r)) }];
  // One scale for the whole tab, not per turn, so turns compare.
  const maxInput = records.reduce((max, r) => Math.max(max, r.input_tokens), 0);
  const maxDuration = records.reduce((max, r) => Math.max(max, requestDurationMs(r) ?? 0), 0);
  const columns: TimelineColumn[] = [
    { key: "time", cell: (r) => <Time record={r} linked={r.request_id !== null && r.request_id === contextRequestId} /> },
    { key: "duration", cell: (r) => <RequestDuration record={r} maxDuration={maxDuration} /> },
    { key: "input", numeric: true, cell: (r) => count(r.input_tokens) },
    // Without any cache read (caching off, or prompts too short to cache) every row would be a 0 % "miss": a miss is only news among hits.
    ...(isEmptyColumn(records, (r) => r.cache_read_tokens) ? [] : [{ key: "cacheHitRate", cell: (r: LlmRequestRecord) => <CacheMeter record={r} maxInput={maxInput} /> }]),
    ...countColumn("cacheRead", (r) => r.cache_read_tokens),
    ...countColumn("cacheWrite", (r) => r.cache_write_tokens),
    { key: "output", numeric: true, cell: (r) => count(r.output_tokens) },
    ...countColumn("reasoning", (r) => r.reasoning_tokens),
    { key: "cost", numeric: true, cell: (r) => <CostCell cost={r.cost} /> },
    // One model in every row is the norm, and the latest request below names it.
    ...(new Set(records.map((r) => r.model_name)).size > 1
      ? [{ key: "model", cell: (r: LlmRequestRecord) => <span className="font-mono text-muted-foreground">{r.model_name ?? "–"}</span> }]
      : []),
  ];

  return (
    <Collapsible title={t("title", { count: records.length })} open>
      <div className="overflow-x-auto">
        <table className="w-full whitespace-nowrap text-xs">
          <thead>
            <tr className="text-xs font-medium text-muted-foreground">
              {columns.map((column) => (
                <th key={column.key} scope="col" className={cn("px-2 py-1.5 font-medium", column.numeric ? "text-right" : "text-left")}>{t(`columns.${column.key}`)}</th>
              ))}
            </tr>
          </thead>
          {groupRequestsByTurn(records).map((group) => (
            <tbody key={group.turnId ?? ""} className="tabular-nums">
              <tr className="border-t border-border">
                <th scope="rowgroup" colSpan={columns.length} className="bg-inset px-2 py-1.5 text-left font-normal">
                  <TurnHeader turnId={group.turnId} turn={turns.find((turn) => turn.turn_id === group.turnId)} onOpenTurn={onOpenTurn} />
                </th>
              </tr>
              {group.records.map((record, index) => (
                <tr key={record.request_id ?? index} className={cn("border-t border-border/60", record.request_id !== null && record.request_id === contextRequestId && "bg-primary/10")}>
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

/**
 * The main column after the time: how long the request took, with its phases in the waterfall's
 * colors. The pill's length is the duration relative to the table's longest, so slow requests stand
 * out. The square root keeps a short tool-call request readable next to a long answer.
 */
function RequestDuration({ record, maxDuration }: { record: LlmRequestRecord; maxDuration: number }) {
  const t = useTranslations("debugView.timeline");
  const format = useFormatter();
  const duration = requestDurationMs(record);
  if (duration === null) return <span className="text-muted-foreground">–</span>;
  const start = Date.parse(record.started_at!);
  return (
    <span className="flex items-center gap-2">
      <span className="w-12 text-right font-medium text-foreground">{t("seconds", { seconds: format.number(duration / 1000, { maximumFractionDigits: 1 }) })}</span>
      {/* Every request of the table may have taken 0 ms. */}
      <ScaledPill share={maxDuration > 0 ? Math.sqrt(duration / maxDuration) : 0} className="w-16">
        <PhaseBar phases={record} start={start} end={start + duration} />
      </ScaledPill>
    </span>
  );
}

/** A pill as long as its share of the fixed-width track, so rows compare; the minimum width keeps a tiny share visible. */
function ScaledPill({ share, className, children }: { share: number; className: string; children: ReactNode }) {
  return (
    <span aria-hidden className={className}>
      <span className="block min-w-[3px]" style={{ width: `${share * 100}%` }}>
        {children}
      </span>
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

/**
 * The pill's length is the request's input relative to the table's largest, its grey part the cache
 * read, so a miss on a big request outweighs one on a small request. Hits are the norm and stay
 * quiet; a miss, the thing to notice, gets the accent.
 */
function CacheMeter({ record, maxInput }: { record: LlmRequestRecord; maxInput: number }) {
  const t = useTranslations("debugView.timeline");
  const format = useFormatter();
  const rate = cacheHitRate(record);
  if (rate === null) return <span className="text-muted-foreground">–</span>;
  const miss = rate === 0;
  return (
    <span className="flex items-center gap-1.5" title={miss ? t("cacheMiss") : undefined}>
      <ScaledPill share={record.input_tokens / maxInput} className="w-10">
        <span className={cn("block h-1.5 overflow-hidden rounded-full", miss ? "bg-warning/30" : "bg-muted")}>
          <span className="block h-full bg-muted-foreground/45" style={{ width: `${rate * 100}%` }} />
        </span>
      </ScaledPill>
      <span className={cn("w-9 text-right", miss ? "font-medium text-warning" : "text-muted-foreground")}>
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
      return <StatusIcon icon={Loader2} label={t(status)} className="animate-spin text-info" />;
    case "failed":
      return <StatusIcon icon={CircleX} label={t(status)} className="text-destructive" />;
    case "interrupted":
      return <StatusIcon icon={CircleSlash} label={t(status)} className="text-muted-foreground" />;
  }
}

/** The status column is gone, so the icon names its status for the screen reader and in a tooltip. */
function StatusIcon({ icon: Icon, label, className }: { icon: LucideIcon; label: string; className: string }) {
  return (
    <span role="img" aria-label={label} title={label} className="inline-flex">
      <Icon aria-hidden className={cn("h-3.5 w-3.5", className)} />
    </span>
  );
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

/** Estimated share of the message text per kind (tool definitions not included), in the colors of the message parts below. */
function InputShapeBar({ shape }: { shape: InputShape }) {
  const t = useTranslations("debugView");
  const format = useFormatter();
  const kinds = INPUT_SHAPE_KINDS.filter((kind) => shape[kind] >= 0.005);
  const percent = (share: number) => format.number(share, { style: "percent", maximumFractionDigits: 0 });
  return (
    <div className="flex basis-full flex-col gap-2 border-t border-border/60 pt-3">
      <span className="text-xs font-medium text-muted-foreground">{t("inputShape")}</span>
      <div className="flex h-2 w-full overflow-hidden rounded-full" role="img" aria-label={kinds.map((kind) => `${t(`shape.${kind}`)} ${percent(shape[kind])}`).join(", ")}>
        {kinds.map((kind) => (
          <span key={kind} className={PART_TONE[SHAPE_TONE[kind]].bar} style={{ width: `${shape[kind] * 100}%` }} />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {kinds.map((kind) => (
          <li key={kind} className="flex items-center gap-1.5">
            <span className={cn("h-2 w-2 rounded-full", PART_TONE[SHAPE_TONE[kind]].bar)} />
            {t(`shape.${kind}`)}
            <span className="tabular-nums text-muted-foreground">{percent(shape[kind])}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function MessageCard({ message, label, highlight = false }: { message: LlmMessage; label: string; highlight?: boolean }) {
  const t = useTranslations("debugView");
  const [raw, setRaw] = useState(false);
  // To the model or from it: the arrow says which way the message went.
  const Direction = message.kind === "request" ? ArrowUpRight : ArrowDownLeft;

  return (
    <section className={cn("rounded-xl border bg-background p-3", highlight ? "border-primary/50" : "border-border")}>
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <Direction aria-hidden className="h-3.5 w-3.5" />
          {label}
        </span>
        <button type="button" aria-pressed={raw} onClick={() => setRaw(!raw)} className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground">
          <Braces className="h-3.5 w-3.5" />
          {raw ? t("showFormatted") : t("showRaw")}
        </button>
      </div>
      {raw ? (
        <Json value={message} />
      ) : (
        <div className="flex flex-col gap-3">
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
      return <Card tone="system" label={t("systemPrompt")}><Content value={part.content} markdown /></Card>;
    case "user-prompt":
      return <Card tone="user" label={t("userPrompt")}><Content value={part.content} markdown /></Card>;
    case "text":
      return <Card tone="assistant" label={t("text")}><Content value={part.content} markdown /></Card>;
    case "thinking":
      return <Card tone="thinking" label={t("thinking")} muted><Content value={part.content} markdown /></Card>;
    case "tool-call":
      return <Card tone="toolCall" label={`${t("toolCall")} · ${part.tool_name}`} badge={part.tool_call_id}><Json value={parseArgs(part.args)} /></Card>;
    case "tool-return":
      return (
        <Card tone={part.outcome === "retried" ? "retry" : "toolReturn"} label={`${t(part.outcome === "retried" ? "toolRetry" : "toolReturn")} · ${part.tool_name}`} badge={part.tool_call_id}>
          <Content value={part.content} clamp />
        </Card>
      );
    case "retry-feedback":
      return <Card tone="retry" label={t("retryFeedback")}><Content value={part.content} clamp /></Card>;
    default:
      // Provider-specific parts (native tools, files, compaction) render as what they are.
      return <Card tone="other" label={part.part_kind}><Json value={part} /></Card>;
  }
}

type PartTone = "system" | "user" | "assistant" | "thinking" | "toolCall" | "toolReturn" | "retry" | "other";

// One icon and color per part kind; the message text bar paints its kinds with the same *bar* colors.
const PART_TONE: Record<PartTone, { icon: LucideIcon; rail: string; text: string; bar: string }> = {
  system: { icon: ScrollText, rail: "border-slate-400 dark:border-slate-500", text: "text-slate-500 dark:text-slate-400", bar: "bg-slate-400 dark:bg-slate-500" },
  user: { icon: User, rail: "border-sky-500", text: "text-sky-600 dark:text-sky-400", bar: "bg-sky-500" },
  assistant: { icon: Bot, rail: "border-emerald-500", text: "text-emerald-600 dark:text-emerald-400", bar: "bg-emerald-500" },
  thinking: { icon: Brain, rail: "border-violet-400 dark:border-violet-500", text: "text-violet-500 dark:text-violet-400", bar: "bg-violet-400 dark:bg-violet-500" },
  toolCall: { icon: Wrench, rail: "border-amber-500", text: "text-amber-600 dark:text-amber-400", bar: "bg-amber-500" },
  toolReturn: { icon: CornerDownLeft, rail: "border-teal-500", text: "text-teal-600 dark:text-teal-400", bar: "bg-teal-500" },
  retry: { icon: RotateCcw, rail: "border-orange-500", text: "text-orange-600 dark:text-orange-400", bar: "bg-orange-500" },
  other: { icon: Box, rail: "border-zinc-300 dark:border-zinc-600", text: "text-muted-foreground", bar: "bg-zinc-300 dark:bg-zinc-600" },
};

const SHAPE_TONE: Record<(typeof INPUT_SHAPE_KINDS)[number], PartTone> = {
  system: "system",
  user: "user",
  assistant: "assistant",
  tool_calls: "toolCall",
  tool_returns: "toolReturn",
  other: "other",
};

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
function Content({ value, markdown = false, clamp = false }: { value: unknown; markdown?: boolean; clamp?: boolean }) {
  if (typeof value !== "string") return <Json value={value} />;
  return markdown ? <MarkdownContent content={value} /> : <Verbatim clamp={clamp}>{value}</Verbatim>;
}

// Long tool output buries the conversation around it, so it starts cut to a preview.
const PREVIEW_LINES = 12;
const PREVIEW_CHARS = 1500;

function Verbatim({ children, clamp = false }: { children: string; clamp?: boolean }) {
  const t = useTranslations("debugView");
  const [expanded, setExpanded] = useState(false);
  const preview = children.split("\n").slice(0, PREVIEW_LINES).join("\n").slice(0, PREVIEW_CHARS);
  const long = clamp && preview !== children;
  return (
    <div className="flex flex-col items-start gap-1">
      <pre className="w-full whitespace-pre-wrap break-words rounded-lg bg-inset p-2 font-mono text-xs">{long && !expanded ? `${preview}…` : children}</pre>
      {long ? (
        <button type="button" onClick={() => setExpanded(!expanded)} className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground">
          {expanded ? t("showLess") : t("showAllLines", { count: children.split("\n").length })}
        </button>
      ) : null}
    </div>
  );
}

/** A string is tool call args the model sent as invalid JSON: shown as sent, not highlighted as JSON. */
function Json({ value }: { value: unknown }) {
  if (typeof value === "string") return <Verbatim>{value}</Verbatim>;
  return <MarkdownContent content={fencedCodeBlock("json", JSON.stringify(value, null, 2))} />;
}

function Card({ label, badge, tone, muted = false, children }: { label: string; badge?: string; tone?: PartTone; muted?: boolean; children: ReactNode }) {
  const style = tone ? PART_TONE[tone] : null;
  const Icon = style?.icon;
  return (
    <div className={cn("min-w-0 text-sm", style ? cn("border-l-2 py-0.5 pl-3", style.rail) : "rounded-lg border border-border/70 p-2.5", muted && "text-muted-foreground")}>
      <div className="mb-1.5 flex min-w-0 items-center justify-between gap-2 text-xs font-medium">
        <span className="flex min-w-0 items-center gap-1.5">
          {Icon ? <Icon aria-hidden className={cn("h-3.5 w-3.5 shrink-0", style.text)} /> : null}
          <span className="truncate">{label}</span>
        </span>
        {badge ? <span className="truncate font-mono text-[11px] text-muted-foreground">{badge}</span> : null}
      </div>
      {children}
    </div>
  );
}

function Collapsible({ title, open = false, children }: { title: string; open?: boolean; children: ReactNode }) {
  return (
    <details open={open} className="group rounded-2xl bg-surface p-3">
      <summary className="cursor-pointer text-sm font-medium">{title}</summary>
      <div className="mt-3 flex flex-col gap-3">{children}</div>
    </details>
  );
}

function StatusBadge({ status }: { status: LlmContextStatus }) {
  const t = useTranslations("debugView.statuses");
  return <span className={cn("inline-flex rounded-full border px-2 py-0.5 text-xs font-medium", STATUS_CLASS[status])}>{t(status)}</span>;
}
