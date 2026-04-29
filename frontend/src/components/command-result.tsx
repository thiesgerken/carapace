"use client";

import {
  decodeAvailableModel,
  decodeSlashCommand,
  type AvailableModelInfo,
  type SlashCommand,
} from "@/lib/api";
import { isRecord, readString } from "@/lib/decoding";

interface HelpData {
  commands: SlashCommand[];
}

interface RuleRow {
  id: string;
  trigger: string;
  mode: string;
  status: string;
}

interface ModelSelection {
  current: string;
  default: string;
}

interface ModelData {
  current?: string;
  default?: string;
  message?: string;
  error?: string;
  models?: Record<string, ModelSelection>;
  available?: AvailableModelInfo[];
}

interface MessageData {
  message?: string;
  error?: string;
}

interface CommandResultViewProps {
  command: string;
  data: unknown;
}

export function CommandResultView({ command, data }: CommandResultViewProps) {
  const helpData = decodeHelpData(data);
  if (command === "help" && helpData) {
    return (
      <div className="my-2 text-sm">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="pb-1 pr-4 font-medium">Command</th>
              <th className="pb-1 font-medium">Description</th>
            </tr>
          </thead>
          <tbody>
            {helpData.commands.map((c) => (
              <tr key={c.command} className="border-b border-border/50">
                <td className="py-1 pr-4 font-mono text-xs">{c.command}</td>
                <td className="py-1 text-muted-foreground">{c.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const rulesData = decodeRulesData(data);
  if (command === "rules" && rulesData) {
    return (
      <div className="my-2 text-sm">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="pb-1 pr-3 font-medium">ID</th>
              <th className="pb-1 pr-3 font-medium">Trigger</th>
              <th className="pb-1 pr-3 font-medium">Mode</th>
              <th className="pb-1 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {rulesData.map((r) => (
              <tr key={r.id} className="border-b border-border/50">
                <td className="py-1 pr-3 font-mono text-xs">{r.id}</td>
                <td className="py-1 pr-3 text-xs">{r.trigger}</td>
                <td className="py-1 pr-3 text-xs">{r.mode}</td>
                <td className="py-1 text-xs">
                  <span
                    className={
                      r.status === "disabled"
                        ? "text-destructive"
                        : r.status === "always-on"
                          ? "text-green-600 dark:text-green-400"
                          : r.status === "activated"
                            ? "text-warning"
                            : "text-muted-foreground"
                    }
                  >
                    {r.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const verboseData = decodeVerboseData(data);
  if (command === "verbose" && verboseData) {
    return <p className="my-1 text-sm text-muted-foreground">{verboseData.message}</p>;
  }

  const modelData = decodeModelData(data);
  if (
    modelData?.models &&
    (command === "models" || command === "model")
  ) {
    const models = modelData.models;
    const available = modelData.available ?? [];
    return (
      <div className="my-2 text-sm">
        {command === "model" && modelData.error ? (
          <p className="mb-2 text-sm text-destructive">{modelData.error}</p>
        ) : null}
        <table className="w-full">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="pb-1 pr-4 font-medium">Type</th>
              <th className="pb-1 pr-4 font-medium">Model</th>
              <th className="pb-1 font-medium">Default</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(models).map(([type, info]) => (
              <tr key={type} className="border-b border-border/50">
                <td className="py-1 pr-4 text-xs font-medium">{type}</td>
                <td className="py-1 pr-4 font-mono text-xs">{info.current}</td>
                <td className="py-1 text-xs text-muted-foreground">
                  {info.current !== info.default ? info.default : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {command === "models" && available.length > 0 && (
          <p className="mt-2 text-xs text-muted-foreground">
            <span className="font-medium">Available: </span>
            {available.map((entry, i) => {
              const id = entry.id;
              if (!id) return null;
              const maxTok = entry.max_input_tokens ?? null;
              return (
                <span key={`${id}-${i}`}>
                  {i > 0 && ", "}
                  <code className="text-foreground">{id}</code>
                  {maxTok != null && (
                    <span className="text-muted-foreground/90">
                      {" "}
                      ({maxTok.toLocaleString()} ctx)
                    </span>
                  )}
                </span>
              );
            })}
          </p>
        )}
        {command === "model" && modelData.message ? (
          <p className="mt-2 text-sm text-muted-foreground">{modelData.message}</p>
        ) : null}
      </div>
    );
  }

  if (
    (command === "model-agent" ||
      command === "model-sentinel" ||
      command === "model-title") &&
    modelData
  ) {
    if (modelData.error)
      return <p className="my-1 text-sm text-destructive">{modelData.error}</p>;
    if (modelData.message)
      return (
        <p className="my-1 text-sm text-muted-foreground">{modelData.message}</p>
      );
    return (
      <div className="my-1 text-sm">
        <p>
          <span className="text-muted-foreground">Current model: </span>
          <span className="font-mono">{modelData.current}</span>
        </p>
        {modelData.default && modelData.default !== modelData.current && (
          <p className="text-xs text-muted-foreground">
            Default: {modelData.default}
          </p>
        )}
      </div>
    );
  }

  if (command === "model" && modelData) {
    if (modelData.error)
      return <p className="my-1 text-sm text-destructive">{modelData.error}</p>;
    if (modelData.message)
      return (
        <p className="my-1 text-sm text-muted-foreground">{modelData.message}</p>
      );
    return (
      <div className="my-1 text-sm">
        <p>
          <span className="text-muted-foreground">Current model: </span>
          <span className="font-mono">{modelData.current}</span>
        </p>
        {modelData.default && modelData.default !== modelData.current && (
          <p className="text-xs text-muted-foreground">
            Default: {modelData.default}
          </p>
        )}
      </div>
    );
  }

  const messageData = decodeMessageData(data);
  if ((command === "disable" || command === "enable") && messageData) {
    if (messageData.error)
      return <p className="my-1 text-sm text-destructive">{messageData.error}</p>;
    return <p className="my-1 text-sm text-muted-foreground">{messageData.message}</p>;
  }

  if (command === "usage" && isUsageData(data)) {
    return <UsageView data={data} />;
  }

  if (command === "budget" && isBudgetData(data)) {
    return <BudgetView data={data} />;
  }

  const plainMessage = decodePlainMessagePayload(data);
  if (plainMessage) {
    if (plainMessage.error) {
      return <p className="my-1 text-sm text-destructive">{plainMessage.error}</p>;
    }
    const failed = /\bfailed\b/i.test(plainMessage.message);
    return (
      <p
        className={`my-1 text-sm whitespace-pre-wrap ${failed ? "text-destructive" : "text-muted-foreground"}`}
      >
        {plainMessage.message}
      </p>
    );
  }

  return (
    <pre className="my-2 rounded-md bg-muted p-2 text-xs font-mono overflow-x-auto">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function decodeHelpData(d: unknown): HelpData | null {
  if (!isRecord(d)) return null;
  const commands = d.commands;
  if (!Array.isArray(commands)) return null;

  const decoded = commands
    .map((entry) => decodeSlashCommand(entry))
    .filter((entry): entry is SlashCommand => entry !== null);

  return { commands: decoded };
}

function decodeRulesData(d: unknown): RuleRow[] | null {
  if (!Array.isArray(d)) return null;

  return d
    .map((entry) => {
      if (!isRecord(entry)) return null;
      const id = readString(entry, "id");
      const trigger = readString(entry, "trigger");
      const mode = readString(entry, "mode");
      const status = readString(entry, "status");
      if (!id || !trigger || !mode || !status) return null;
      return { id, trigger, mode, status };
    })
    .filter((entry): entry is RuleRow => entry !== null);
}

function decodeVerboseData(d: unknown): { message: string } | null {
  if (!isRecord(d)) return null;
  const message = readString(d, "message");
  return message === undefined ? null : { message };
}

function decodeModelSelections(
  raw: unknown,
): Record<string, ModelSelection> | undefined {
  if (!isRecord(raw)) return undefined;

  const entries = Object.entries(raw)
    .map(([key, value]) => {
      if (!isRecord(value)) return null;
      const current = readString(value, "current");
      const fallback = readString(value, "default");
      if (current === undefined || fallback === undefined) return null;
      return [key, { current, default: fallback }] as const;
    })
    .filter(
      (
        entry,
      ): entry is readonly [string, ModelSelection] => entry !== null,
    );

  return Object.fromEntries(entries);
}

function decodeModelData(d: unknown): ModelData | null {
  if (!isRecord(d)) return null;

  const available = Array.isArray(d.available)
    ? d.available
      .map((entry) => decodeAvailableModel(entry))
      .filter((entry): entry is AvailableModelInfo => entry !== null)
    : undefined;

  return {
    current: readString(d, "current"),
    default: readString(d, "default"),
    message: readString(d, "message"),
    error: readString(d, "error"),
    models: decodeModelSelections(d.models),
    available,
  };
}

function decodeMessageData(d: unknown): MessageData | null {
  if (!isRecord(d)) return null;
  const message = readString(d, "message");
  const error = readString(d, "error");
  if (message === undefined && error === undefined) return null;
  return { message, error };
}

/** Object with only message (and optional error) — avoids JSON dump for simple slash results. */
function decodePlainMessagePayload(
  d: unknown,
): { message: string; error?: string } | null {
  if (!isRecord(d)) return null;
  const message = readString(d, "message");
  if (message === undefined) return null;
  const error = readString(d, "error");
  for (const k of Object.keys(d)) {
    if (k === "message") continue;
    if (k === "error" && error !== undefined) continue;
    return null;
  }
  return error === undefined ? { message } : { message, error };
}

interface UsageBucket {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  input_audio_tokens: number;
  output_audio_tokens: number;
  cache_audio_read_tokens: number;
  requests: number;
}

interface BudgetGaugeData {
  key: "input" | "output" | "cost";
  label: string;
  current_value: string;
  limit_value: string;
  remaining_value?: string | null;
  fill_pct: number;
  reached: boolean;
  unavailable_reason?: string | null;
}

/** % of tiktoken mass over the prompt only (sum 100); unrelated to API billing tokens. */
interface LastLlmBreakdownPct {
  system: number | null;
  user: number | null;
  assistant: number | null;
  tool_calls: number | null;
  tool_returns: number | null;
  other: number | null;
}

interface LastLlmRequestRow {
  source: string;
  input_tokens: number;
  output_tokens: number;
  context_size: number;
  breakdown_pct: LastLlmBreakdownPct;
  /** Config (or default) context window used for ``context_used_pct``. */
  context_cap_tokens?: number;
  /** Share of context cap used by input+output tokens for this request (0–100). */
  context_used_pct?: number;
}

interface UsagePayload {
  models: Record<string, UsageBucket>;
  categories: Record<string, UsageBucket>;
  total_input: number;
  total_output: number;
  costs?: Record<string, string>;
  category_costs?: Record<string, string>;
  budget_gauges?: BudgetGaugeData[];
  last_llm_agent?: LastLlmRequestRow | null;
  last_llm_sentinel?: LastLlmRequestRow | null;
}

interface BudgetPayload {
  gauges: BudgetGaugeData[];
  message?: string;
  error?: string;
  usage_hint?: string;
}

function isUsageData(d: unknown): d is UsagePayload {
  return !!d && typeof d === "object" && "models" in d && "categories" in d;
}

function isBudgetData(d: unknown): d is BudgetPayload {
  return !!d && typeof d === "object" && "gauges" in d;
}

function fmt(n: number): string {
  return n.toLocaleString();
}

function costColor(val: number): string {
  if (val >= 0.25) return "text-red-600 dark:text-red-400";
  if (val >= 0.1) return "text-yellow-600 dark:text-yellow-400";
  return "text-green-600 dark:text-green-400";
}

function fmtCost(val: string): string {
  const n = parseFloat(val);
  return n ? `$${n.toFixed(4)}` : "-";
}

function fmtPctCell(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${v.toFixed(1)}%`;
}

function lastRequestRowsShowOtherPct(rows: LastLlmRequestRow[]): boolean {
  return rows.some((r) => (r.breakdown_pct?.other ?? 0) > 0);
}

function UsageView({ data }: { data: UsagePayload }) {
  const budgetGauges = Array.isArray(data.budget_gauges) ? data.budget_gauges : [];
  const allBuckets = [
    ...Object.values(data.models),
    ...Object.values(data.categories),
  ];
  const hasCache = allBuckets.some(
    (b) => b.cache_read_tokens || b.cache_write_tokens,
  );
  const costs = data.costs ?? {};
  const categoryCosts = data.category_costs ?? {};
  const hasCosts = Object.entries(costs).some(
    ([k, v]) => k !== "total" && v !== "0",
  );
  const isEmpty =
    Object.keys(data.models).length === 0 &&
    Object.keys(data.categories).length === 0 &&
    budgetGauges.length === 0;
  if (isEmpty) {
    return (
      <p className="my-1 text-sm text-muted-foreground">
        No token usage recorded yet.
      </p>
    );
  }

  function renderTable(
    title: string,
    rows: Record<string, UsageBucket>,
    showCost: boolean = false,
    rowCosts: Record<string, string> | undefined = undefined,
  ) {
    const costLookup = rowCosts ?? costs;
    return (
      <div className="my-2 text-sm">
        <p className="mb-1 text-xs font-medium text-muted-foreground">
          {title}
        </p>
        <table className="w-full">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="pb-1 pr-3 font-medium">Source</th>
              <th className="pb-1 pr-3 font-medium text-right">Input</th>
              <th className="pb-1 pr-3 font-medium text-right">Output</th>
              {hasCache && (
                <th className="pb-1 pr-3 font-medium text-right">Cache Read</th>
              )}
              {hasCache && (
                <th className="pb-1 pr-3 font-medium text-right">
                  Cache Write
                </th>
              )}
              <th className="pb-1 pr-3 font-medium text-right">Requests</th>
              {showCost && hasCosts && (
                <th className="pb-1 font-medium text-right">Cost</th>
              )}
            </tr>
          </thead>
          <tbody>
            {Object.entries(rows).map(([name, u]) => (
              <tr key={name} className="border-b border-border/50">
                <td className="py-1 pr-3 font-mono text-xs">{name}</td>
                <td className="py-1 pr-3 text-xs text-right">
                  {fmt(u.input_tokens)}
                </td>
                <td className="py-1 pr-3 text-xs text-right">
                  {fmt(u.output_tokens)}
                </td>
                {hasCache && (
                  <td className="py-1 pr-3 text-xs text-right">
                    {fmt(u.cache_read_tokens)}
                  </td>
                )}
                {hasCache && (
                  <td className="py-1 pr-3 text-xs text-right">
                    {fmt(u.cache_write_tokens)}
                  </td>
                )}
                <td className="py-1 pr-3 text-xs text-right">{u.requests}</td>
                {showCost && hasCosts && (
                  <td
                    className={`py-1 text-xs text-right ${costColor(parseFloat(costLookup[name] ?? "0"))}`}
                  >
                    {fmtCost(costLookup[name] ?? "0")}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const total = data.total_input + data.total_output;
  const totalCost = costs.total ?? "0";
  const costStr =
    totalCost !== "0" ? (
      <span className={costColor(parseFloat(totalCost))}>
        {" "}
        | {fmtCost(totalCost)}
      </span>
    ) : null;

  const lastRequestRows = (
    [data.last_llm_agent, data.last_llm_sentinel] as const
  ).filter(
    (r): r is LastLlmRequestRow =>
      r != null && typeof r.context_size === "number" && r.context_size > 0,
  );
  const showOtherPctCol = lastRequestRowsShowOtherPct(lastRequestRows);

  return (
    <div>
      <p className="mb-2 text-xs text-muted-foreground">
        Total: {fmt(total)} tokens ({fmt(data.total_input)} in +{" "}
        {fmt(data.total_output)} out){costStr}
      </p>
      {budgetGauges.length > 0 ? <BudgetTable gauges={budgetGauges} /> : null}
      {Object.keys(data.models).length > 0 &&
        renderTable("By Model", data.models, true)}
      {Object.keys(data.categories).length > 0 &&
        renderTable("By Category", data.categories, true, categoryCosts)}
      {lastRequestRows.length > 0 ? (
        <div className="mt-2 text-sm">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            Context
          </p>
          <table className="w-full">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="pb-1 pr-2 font-medium">Source</th>
                <th className="pb-1 pr-2 font-medium text-right">Tokens</th>
                <th className="pb-1 pr-2 font-medium text-right">System %</th>
                <th className="pb-1 pr-2 font-medium text-right">User %</th>
                <th className="pb-1 pr-2 font-medium text-right">
                  Assistant %
                </th>
                <th className="pb-1 pr-2 font-medium text-right">
                  Tool Calls %
                </th>
                <th className="pb-1 pr-2 font-medium text-right">
                  Tool Outputs %
                </th>
                {showOtherPctCol ? (
                  <th className="pb-1 font-medium text-right">Other %</th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {lastRequestRows.map((r) => (
                <tr
                  key={r.source}
                  className="border-b border-border/50 font-mono text-xs"
                >
                  <td className="py-1 pr-2">{r.source}</td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {fmt(r.context_size)}
                    {typeof r.context_used_pct === "number" ? (
                      <span className="text-muted-foreground">
                        {" "}
                        ({r.context_used_pct.toFixed(1)}%)
                      </span>
                    ) : null}
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {fmtPctCell(r.breakdown_pct?.system)}
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {fmtPctCell(r.breakdown_pct?.user)}
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {fmtPctCell(r.breakdown_pct?.assistant)}
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {fmtPctCell(r.breakdown_pct?.tool_calls)}
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {fmtPctCell(r.breakdown_pct?.tool_returns)}
                  </td>
                  {showOtherPctCol ? (
                    <td className="py-1 text-right tabular-nums">
                      {fmtPctCell(r.breakdown_pct?.other)}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function BudgetView({ data }: { data: BudgetPayload }) {
  if (data.error) {
    return <p className="my-1 text-sm text-destructive">{data.error}</p>;
  }
  if (data.gauges.length === 0) {
    return (
      <div className="my-1 text-sm text-muted-foreground">
        <p>{data.message ?? "No session budgets configured."}</p>
        {data.usage_hint ? <p className="mt-1 text-xs">{data.usage_hint}</p> : null}
      </div>
    );
  }
  return (
    <div className="my-2 text-sm">
      {data.message ? (
        <p className="mb-2 text-sm text-muted-foreground">{data.message}</p>
      ) : null}
      {data.usage_hint ? (
        <p className="mb-2 text-xs text-muted-foreground">{data.usage_hint}</p>
      ) : null}
      <BudgetTable gauges={data.gauges} />
    </div>
  );
}

function BudgetTable({ gauges }: { gauges: BudgetGaugeData[] }) {
  return (
    <div className="my-2 text-sm">
      <p className="mb-1 text-xs font-medium text-muted-foreground">
        Session Budgets
      </p>
      <table className="w-full">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="pb-1 pr-3 font-medium">Metric</th>
            <th className="pb-1 pr-3 font-medium text-right">Current</th>
            <th className="pb-1 pr-3 font-medium text-right">Limit</th>
            <th className="pb-1 pr-3 font-medium text-right">Remaining</th>
            <th className="pb-1 font-medium text-right">Used</th>
          </tr>
        </thead>
        <tbody>
          {gauges.map((gauge) => (
            <tr key={gauge.key} className="border-b border-border/50">
              <td className="py-1 pr-3 text-xs font-medium">{gauge.label}</td>
              <td className="py-1 pr-3 text-xs text-right tabular-nums">
                {gauge.current_value}
              </td>
              <td className="py-1 pr-3 text-xs text-right tabular-nums">
                {gauge.limit_value}
              </td>
              <td className="py-1 pr-3 text-xs text-right tabular-nums">
                {gauge.remaining_value ?? "—"}
              </td>
              <td className="py-1 text-xs text-right tabular-nums">
                {gauge.unavailable_reason ? (
                  <span className="text-destructive">blocked</span>
                ) : (
                  `${gauge.fill_pct.toFixed(1)}%`
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
