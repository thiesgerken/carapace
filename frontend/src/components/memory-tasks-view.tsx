"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import { Activity, ArrowDown, Ban, Cpu, Loader2, Play, RotateCcw, Shapes } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { differsFrom, FilterBar, FilterSelect, PeriodPicker } from "@/components/memory-filter-bar";
import {
  buttonClassName,
  ExpandButton,
  PickMatchingRow,
  SelectionBar,
  TaskStatusBadge,
  togglesRow,
} from "@/components/memory-ui";
import { MemoryRunDialog } from "@/components/memory-run-dialog";
import { MemoryTaskDetail } from "@/components/memory-task-detail";
import { useMemoryStatus } from "@/components/memory-status";
import { cancelMemoryTasks, listMemoryTasks, runMemoryTasks } from "@/lib/api";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/format-time";
import {
  formatTokenEstimate,
  formatTokens,
  formatUsd,
  MEMORY_TASK_KINDS,
  MEMORY_TASK_STATUSES,
  missingSourceCount,
  sourceTasksForm,
  taskActivityAt,
  taskRunModel,
  toTaskFilter,
  toTaskSelection,
  type TaskFilterForm,
  type TaskPick,
  weekLabel,
} from "@/lib/memory";
import type { MemoryTaskListResponse, MemoryTaskSelection, MemoryTaskSort, MemoryTaskStatus, MemoryTaskView } from "@/lib/types";
import { cn } from "@/lib/utils";

const NEWEST_BATCH = 50;
const DEFAULT_FORM: TaskFilterForm = { status: "unfinished", kind: "", period: "", model: "" };
const NO_PICK: TaskPick = { kind: "ids", ids: [] };
const COLUMN_COUNT = 9;

export function MemoryTasksView({ server, token, initialStatus = null }: {
  server: string;
  token: string;
  /** Preselects the status filter (from ?status=, e.g. the home page's link to failed tasks); unknown values are ignored. */
  initialStatus?: string | null;
}) {
  const t = useTranslations("memory.tasks");
  const tStatuses = useTranslations("memory.taskStatuses");
  const tKinds = useTranslations("memory.taskKinds");
  const tSidebar = useTranslations("sidebar");
  const locale = useLocale();
  const { status, refreshStatus } = useMemoryStatus();
  const [form, setForm] = useState<TaskFilterForm>(() => (
    MEMORY_TASK_STATUSES.some((status) => status === initialStatus)
      ? { ...DEFAULT_FORM, status: initialStatus as MemoryTaskStatus }
      : DEFAULT_FORM
  ));
  const filter = useMemo(() => toTaskFilter(form), [form]);
  const [sort, setSort] = useState<MemoryTaskSort>("activity");
  const [now, setNow] = useState(() => Date.now());
  const [page, setPage] = useState<MemoryTaskListResponse | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pick, setPick] = useState<TaskPick>(NO_PICK);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [runSelection, setRunSelection] = useState<MemoryTaskSelection | null>(null);
  const [busy, setBusy] = useState(false);

  // `status` is a dependency on purpose: it changes on every poll and after every action.
  // ponytail: a reload drops pages fetched via "Load more"; keep a page count if that annoys.
  useEffect(() => {
    let cancelled = false;
    listMemoryTasks(server, filter, sort)
      .then((result) => {
        if (cancelled) return;
        setPage(result);
        setNow(Date.now());
        setError(null);
      })
      .catch((listError: unknown) => {
        if (!cancelled) setError(listError instanceof Error ? listError.message : String(listError));
      });
    return () => {
      cancelled = true;
    };
  }, [server, filter, sort, status]);

  const items = page?.items ?? [];
  const total = page?.total ?? 0;
  const visibleIds = items.map((task) => task.id);
  const allVisiblePicked = pick.kind === "matching" || (items.length > 0 && visibleIds.every((id) => pick.ids.includes(id)));
  const pickedCount = pick.kind === "matching" ? total : pick.ids.length;
  const models = status?.models ?? null;
  const modelOptions = [...new Set([
    ...(models ? Object.values(models) : []),
    ...items.map((task) => taskRunModel(task, models)).filter((model): model is string => model !== null),
    ...(form.model ? [form.model] : []),
  ])].sort();

  function updateForm(patch: Partial<TaskFilterForm>): void {
    setForm((current) => ({ ...current, ...patch }));
    setPick(NO_PICK);
  }

  function togglePicked(id: number): void {
    setPick((current) => current.kind === "ids"
      ? { kind: "ids", ids: current.ids.includes(id) ? current.ids.filter((picked) => picked !== id) : [...current.ids, id] }
      : current);
  }

  async function loadMore(): Promise<void> {
    if (!page?.next_cursor) return;
    setLoadingMore(true);
    try {
      const next = await listMemoryTasks(server, filter, sort, page.next_cursor);
      setPage({ ...next, items: [...page.items, ...next.items] });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      setLoadingMore(false);
    }
  }

  async function act(action: () => Promise<{ count: number }>, message: (count: number) => string): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const { count } = await action();
      setNotice(message(count));
      setPick(NO_PICK);
      await refreshStatus();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : String(actionError));
    } finally {
      setBusy(false);
    }
  }

  function costCell(task: MemoryTaskView): string {
    if (task.provenance) {
      return task.provenance.cost_usd !== null
        ? formatUsd(task.provenance.cost_usd, locale)
        : `${formatTokens(task.provenance.input_tokens, locale)} in · ${formatTokens(task.provenance.output_tokens, locale)} out`;
    }
    if (task.estimate) {
      return task.estimate.cost_usd !== null
        ? `~${formatUsd(task.estimate.cost_usd, locale)}`
        : formatTokenEstimate(task.estimate.input_tokens, task.estimate.output_tokens_cap, locale);
    }
    return "—";
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
      <div className="space-y-3">
        <FilterBar
          count={(
            <>
              {t("matching", { count: total })}
              {page && page.estimate.task_count > 0
                ? ` · ${t("estimate", {
                  cost: page.estimate.unpriced_count === page.estimate.task_count
                    ? formatTokenEstimate(page.estimate.input_tokens, page.estimate.output_tokens_cap, locale)
                    : formatUsd(page.estimate.cost_usd, locale),
                })}`
                : null}
            </>
          )}
          canReset={differsFrom(form, DEFAULT_FORM)}
          onReset={() => updateForm(DEFAULT_FORM)}
          actions={(
            <button
              type="button"
              disabled={busy || total === 0}
              onClick={() => setRunSelection({ filter, newest: NEWEST_BATCH })}
              className={cn(buttonClassName, "h-9")}
            >
              <Play className="h-4 w-4" />
              {t("runNewest", { count: NEWEST_BATCH })}
            </button>
          )}
        >
          <FilterSelect
            icon={Activity}
            label={t("filters.status")}
            anyLabel={t("filters.anyStatus")}
            value={form.status}
            active={form.status !== DEFAULT_FORM.status}
            options={[
              { value: "unfinished" as const, label: t("filters.unfinished") },
              ...MEMORY_TASK_STATUSES.map((value) => ({ value, label: tStatuses(value) })),
            ]}
            onChange={(status) => updateForm({ status })}
          />
          <FilterSelect
            icon={Shapes}
            label={t("filters.kind")}
            anyLabel={t("filters.anyKind")}
            value={form.kind}
            active={form.kind !== DEFAULT_FORM.kind}
            options={MEMORY_TASK_KINDS.map((value) => ({ value, label: tKinds(value) }))}
            onChange={(kind) => updateForm({ kind })}
          />
          <PeriodPicker label={t("filters.period")} value={form.period} active={form.period !== DEFAULT_FORM.period} allowMonth onChange={(period) => updateForm({ period })} />
          <FilterSelect
            icon={Cpu}
            label={t("filters.model")}
            anyLabel={t("filters.anyModel")}
            value={form.model}
            active={form.model !== DEFAULT_FORM.model}
            options={modelOptions.map((value) => ({ value, label: value }))}
            onChange={(model) => updateForm({ model })}
          />
        </FilterBar>

        {error ? <div className="rounded-lg border border-border bg-background px-4 py-2 text-sm text-destructive">{error}</div> : null}
        {notice ? (
          <div className="flex items-center justify-between rounded-lg border border-border bg-background px-4 py-2 text-sm">
            <span>{notice}</span>
            <button type="button" onClick={() => setNotice(null)} className="text-xs text-muted-foreground underline underline-offset-2">{t("dismiss")}</button>
          </div>
        ) : null}

        {pickedCount > 0 ? (
          <SelectionBar count={pickedCount} onClear={() => setPick(NO_PICK)}>
            <button type="button" disabled={busy} onClick={() => setRunSelection(toTaskSelection(pick, filter))} className={buttonClassName}>
              <Play className="h-4 w-4" />
              {t("runPicked")}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void act(() => cancelMemoryTasks(server, toTaskSelection(pick, filter)), (count) => t("cancelled", { count }))}
              className={buttonClassName}
            >
              <Ban className="h-4 w-4" />
              {t("cancelPicked")}
            </button>
          </SelectionBar>
        ) : null}

        <div className="overflow-x-auto rounded-lg border border-border bg-background">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border text-xs text-muted-foreground">
              <tr>
                <th className="w-10 px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label={t("pickPage")}
                    checked={allVisiblePicked}
                    disabled={items.length === 0}
                    onChange={() => setPick(allVisiblePicked ? NO_PICK : { kind: "ids", ids: visibleIds })}
                  />
                </th>
                <th className="px-3 py-2 font-medium">{t("columns.kind")}</th>
                <SortableHeader label={t("columns.target")} title={t("sortBy.period")} active={sort === "period"} onSort={() => setSort("period")} />
                <th className="px-3 py-2 font-medium">{t("columns.status")}</th>
                <th className="px-3 py-2 font-medium">{t("columns.model")}</th>
                <th className="px-3 py-2 font-medium">{t("columns.version")}</th>
                <SortableHeader label={t("columns.activity")} title={t("sortBy.activity")} active={sort === "activity"} onSort={() => setSort("activity")} />
                <th className="px-3 py-2 text-right font-medium">{t("columns.cost")}</th>
                <th className="w-10 px-3 py-2"><span className="sr-only">{t("columns.actions")}</span></th>
              </tr>
              {allVisiblePicked && total > items.length ? (
                <PickMatchingRow
                  colSpan={COLUMN_COUNT}
                  total={total}
                  matching={pick.kind === "matching"}
                  onPickMatching={() => setPick({ kind: "matching" })}
                  onClear={() => setPick(NO_PICK)}
                />
              ) : null}
            </thead>
            <tbody>
              {page === null && error === null ? (
                <tr><td colSpan={COLUMN_COUNT} className="px-3 py-6 text-center text-muted-foreground"><Loader2 className="mx-auto h-4 w-4 animate-spin" /></td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={COLUMN_COUNT} className="px-3 py-6 text-center text-muted-foreground">{t("empty")}</td></tr>
              ) : items.map((task) => {
                const expanded = expandedId === task.id;
                return (
                  <Fragment key={task.id}>
                    <tr
                      onClick={(event) => {
                        if (togglesRow(event.target)) setExpandedId(expanded ? null : task.id);
                      }}
                      className={cn("cursor-pointer border-b border-border/60 align-top last:border-b-0 hover:bg-muted/30", expanded && "bg-muted/40")}
                    >
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          aria-label={t("pickTask", { target: task.target_label })}
                          checked={pick.kind === "matching" || pick.ids.includes(task.id)}
                          disabled={pick.kind === "matching"}
                          onChange={() => togglePicked(task.id)}
                        />
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-xs">{tKinds(task.kind)}</td>
                      <td className="px-3 py-2">
                        {task.target_label}
                        {task.kind === "week_digest" ? <span className="ml-2 text-xs text-muted-foreground">{weekLabel(task.target, locale, true)}</span> : null}
                        {task.status === "failed" && task.error ? (
                          <div className="mt-0.5 line-clamp-1 text-xs text-destructive">{task.error}</div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2">
                        <TaskStatusBadge status={task.status} />
                        {task.blocked_reason === "budget" ? <div className="text-xs text-amber-700 dark:text-amber-400">{t("blockedBudget")}</div> : null}
                        <DependencyHint task={task} onShowSources={() => updateForm(sourceTasksForm(task))} />
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">{taskRunModel(task, models) ?? "—"}</td>
                      <td className="px-3 py-2 font-mono text-xs">{task.provenance?.carapace_version ?? "—"}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground" title={formatAbsoluteTime(taskActivityAt(task), locale)}>
                        {formatRelativeTime(taskActivityAt(task), locale, now, tSidebar("time.justNow"))}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{costCell(task)}</td>
                      <td className="px-3 py-1.5">
                        <div className="flex items-center justify-end gap-1">
                          {task.status === "failed" ? (
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void act(() => runMemoryTasks(server, { selection: { ids: [task.id] } }), (count) => t("retried", { count }))}
                              title={t("retry")}
                              aria-label={t("retry")}
                              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
                            >
                              <RotateCcw className="h-3.5 w-3.5" />
                            </button>
                          ) : null}
                          <ExpandButton
                            expanded={expanded}
                            controls={taskDetailId(task.id)}
                            label={t(expanded ? "collapse" : "expand", { target: task.target_label })}
                            onToggle={() => setExpandedId(expanded ? null : task.id)}
                          />
                        </div>
                      </td>
                    </tr>
                    {expanded ? (
                      <tr id={taskDetailId(task.id)} className="border-b border-border/60 bg-muted/40">
                        <td colSpan={COLUMN_COUNT} className="px-3 pb-3">
                          <MemoryTaskDetail server={server} task={task} models={models} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>

        {page?.next_cursor ? (
          <button type="button" onClick={() => void loadMore()} disabled={loadingMore} className={buttonClassName}>
            {loadingMore ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {t("loadMore")}
          </button>
        ) : null}
      </div>

      {runSelection ? (
        <MemoryRunDialog
          server={server}
          token={token}
          selection={runSelection}
          kinds={runSelection.ids
            ? items.filter((task) => runSelection.ids?.includes(task.id)).map((task) => task.kind)
            : runSelection.filter?.kind ?? MEMORY_TASK_KINDS}
          onClose={() => setRunSelection(null)}
          onQueued={(count) => {
            setNotice(t("queued", { count }));
            setPick(NO_PICK);
            void refreshStatus();
          }}
        />
      ) : null}
    </div>
  );
}

/** Why a digest waits, or which sources it would run without, linked to the period's source tasks. */
function DependencyHint({ task, onShowSources }: { task: MemoryTaskView; onShowSources: () => void }) {
  const t = useTranslations("memory.tasks");
  const dependencies = task.dependencies;
  if (dependencies === null || task.status === "done" || task.status === "cancelled") return null;
  const week = task.kind === "week_digest";
  const missing = missingSourceCount(dependencies);
  const text = task.blocked_reason === "dependencies"
    ? t(week ? "waitingExtractions" : "waitingSources", { count: dependencies.waiting })
    : missing > 0
      ? t(week ? "missingExtractions" : "missingSources", { count: missing })
      : null;
  if (text === null) return null;
  return (
    <button
      type="button"
      title={t("showSources")}
      onClick={onShowSources}
      className="block text-left text-xs text-amber-700 underline-offset-2 hover:underline dark:text-amber-400"
    >
      {text}
    </button>
  );
}

function SortableHeader({ label, title, active, onSort }: { label: string; title: string; active: boolean; onSort: () => void }) {
  return (
    <th aria-sort={active ? "descending" : "none"} className="px-3 py-2 font-medium">
      <button type="button" title={title} onClick={onSort} className={cn("inline-flex items-center gap-1 hover:text-foreground", active && "text-foreground")}>
        {label}
        {active ? <ArrowDown className="h-3 w-3" /> : null}
      </button>
    </th>
  );
}


function taskDetailId(taskId: number): string {
  return `memory-task-detail-${taskId}`;
}
