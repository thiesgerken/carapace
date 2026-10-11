"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Play } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useMemoryStatus } from "@/components/memory-status";
import { ModelPicker } from "@/components/model-picker";
import { estimateMemoryTasks, fetchModels, runMemoryTasks, type AvailableModelInfo } from "@/lib/api";
import { exceedsBudget, formatTokenEstimate, formatTokens, formatUsd, remainingBudget, roleDefaultModels } from "@/lib/memory";
import type { MemoryRunEstimate, MemoryTaskKind, MemoryTaskSelection } from "@/lib/types";

interface MemoryRunDialogProps {
  server: string;
  token: string;
  selection: MemoryTaskSelection;
  /** Kinds of the selected tasks, to name the models the role default resolves to. */
  kinds: readonly MemoryTaskKind[];
  onClose: () => void;
  onQueued: (count: number) => void;
}

/** An estimate outcome, tagged with the model override and dependency choice it was computed for. */
type EstimateOutcome = { model: string | null; includeDependencies: boolean } & ({ total: MemoryRunEstimate } | { error: string });

export function MemoryRunDialog({ server, token, selection, kinds, onClose, onQueued }: MemoryRunDialogProps) {
  const t = useTranslations("memory.run");
  const locale = useLocale();
  const { status } = useMemoryStatus();
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const [models, setModels] = useState<AvailableModelInfo[]>([]);
  const [modelOverride, setModelOverride] = useState<string | null>(null);
  const [includeDependencies, setIncludeDependencies] = useState(false);
  const [outcome, setOutcome] = useState<EstimateOutcome | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  useEffect(() => {
    void fetchModels(server, token).then(setModels);
  }, [server, token]);

  useEffect(() => {
    let cancelled = false;
    const tag = { model: modelOverride, includeDependencies };
    estimateMemoryTasks(server, { selection, model_override: modelOverride, include_dependencies: includeDependencies })
      .then((total) => {
        if (!cancelled) setOutcome({ ...tag, total });
      })
      .catch((estimateError: unknown) => {
        if (!cancelled) setOutcome({ ...tag, error: estimateError instanceof Error ? estimateError.message : String(estimateError) });
      });
    return () => {
      cancelled = true;
    };
  }, [server, selection, modelOverride, includeDependencies]);

  async function handleRun(): Promise<void> {
    setRunning(true);
    setRunError(null);
    try {
      const { count } = await runMemoryTasks(server, { selection, model_override: modelOverride, include_dependencies: includeDependencies });
      onQueued(count);
      dialogRef.current?.close();
    } catch (caught) {
      setRunError(caught instanceof Error ? caught.message : String(caught));
      setRunning(false);
    }
  }

  // Keyed by model and dependency choice: a stale outcome reads as loading, and re-picking the current model keeps its estimate.
  const current = outcome?.model === modelOverride && outcome.includeDependencies === includeDependencies ? outcome : null;
  const estimate = current && "total" in current ? current.total : null;
  const runCount = estimate ? estimate.task_count + estimate.unestimated : null;
  const error = (current && "error" in current ? current.error : null) ?? runError;
  const remaining = status ? remainingBudget(status) : null;
  const overBudget = estimate !== null && status !== null && exceedsBudget(estimate, status);
  const defaultModels = status ? roleDefaultModels(kinds, status.models) : null;

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      aria-labelledby="memory-run-title"
      className="m-auto w-[min(32rem,calc(100vw-2rem))] overflow-visible rounded-2xl border border-border bg-background p-0 text-foreground shadow-xl backdrop:bg-black/40"
    >
      <div className="space-y-4 p-5">
        <h2 id="memory-run-title" className="text-lg font-semibold tracking-tight">{t("title")}</h2>

        {current === null ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("estimating")}
          </div>
        ) : runCount === 0 ? (
          <p className="text-sm text-muted-foreground">{t("nothingToRun")}</p>
        ) : estimate ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-sm">
            <dt className="text-muted-foreground">{t("tasks")}</dt>
            <dd className="tabular-nums">{runCount?.toLocaleString(locale)}</dd>
            <dt className="text-muted-foreground">{t("inputTokens")}</dt>
            <dd className="tabular-nums">{formatTokens(estimate.input_tokens, locale)}</dd>
            <dt className="text-muted-foreground">{t("cost")}</dt>
            <dd className="tabular-nums">
              {estimate.task_count > 0 && estimate.unpriced_count === estimate.task_count
                ? formatTokenEstimate(estimate.input_tokens, estimate.output_tokens_cap, locale)
                : `~${formatUsd(estimate.cost_usd, locale)}`}
              {estimate.unpriced_count > 0 && estimate.unpriced_count < estimate.task_count ? (
                <span className="ml-2 text-muted-foreground">{t("unpriced", { count: estimate.unpriced_count })}</span>
              ) : null}
            </dd>
            <dt className="text-muted-foreground">{t("remaining")}</dt>
            <dd className="tabular-nums">
              {remaining?.usd != null ? formatUsd(remaining.usd, locale) : null}
              {remaining?.usd != null && remaining.tokens != null ? " · " : null}
              {remaining?.tokens != null ? `${formatTokens(remaining.tokens, locale)} ${t("tokens")}` : null}
              {remaining?.usd == null && remaining?.tokens == null ? t("noLimit") : null}
            </dd>
          </dl>
        ) : null}

        {estimate && estimate.unestimated > 0 ? <p className="text-sm text-muted-foreground">{t("unestimated", { count: estimate.unestimated })}</p> : null}

        {overBudget ? <p className="text-sm text-amber-700 dark:text-amber-400">{t("overBudget")}</p> : null}

        {estimate && estimate.missing_dependencies > 0 ? (
          includeDependencies ? (
            <p className="text-sm text-muted-foreground">{t("dependenciesAdded", { count: estimate.missing_dependencies })}</p>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-amber-700 dark:text-amber-400">
              <span>{t("missingDependencies", { count: estimate.missing_dependencies })}</span>
              <button
                type="button"
                onClick={() => setIncludeDependencies(true)}
                disabled={running}
                className="rounded-md px-2 py-1 font-medium text-foreground underline underline-offset-2 hover:bg-muted disabled:opacity-50"
              >
                {t("addDependencies", { count: estimate.missing_dependencies })}
              </button>
            </div>
          )
        ) : null}

        <div className="space-y-1.5">
          <span className="text-xs font-medium text-muted-foreground">{t("model")}</span>
          <ModelPicker
            value={modelOverride}
            entries={models}
            onChange={(model) => {
              setModelOverride(model);
              setRunError(null);
            }}
            disabled={running}
            defaultLabel={defaultModels ? t("roleDefaultResolved", { models: defaultModels }) : t("roleDefault")}
          />
        </div>

        {error ? <p className="text-sm text-destructive">{error}</p> : null}

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={() => dialogRef.current?.close()}
            className="rounded-lg px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            onClick={() => void handleRun()}
            disabled={running || !runCount}
            className="inline-flex items-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {t("confirm")}
          </button>
        </div>
      </div>
    </dialog>
  );
}
