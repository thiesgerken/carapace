"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Play } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useMemoryStatus } from "@/components/memory-status";
import { ModelPicker } from "@/components/model-picker";
import { estimateMemoryTasks, fetchModels, runMemoryTasks, type AvailableModelInfo } from "@/lib/api";
import { formatTokens, formatUsd, remainingBudget } from "@/lib/memory";
import type { MemoryEstimateTotal, MemoryTaskSelection } from "@/lib/types";

interface MemoryRunDialogProps {
  server: string;
  token: string;
  selection: MemoryTaskSelection;
  onClose: () => void;
  onQueued: (count: number) => void;
}

export function MemoryRunDialog({ server, token, selection, onClose, onQueued }: MemoryRunDialogProps) {
  const t = useTranslations("memory.run");
  const locale = useLocale();
  const { status } = useMemoryStatus();
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const [models, setModels] = useState<AvailableModelInfo[]>([]);
  const [modelOverride, setModelOverride] = useState<string | null>(null);
  const [estimate, setEstimate] = useState<MemoryEstimateTotal | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  useEffect(() => {
    void fetchModels(server, token).then(setModels);
  }, [server, token]);

  useEffect(() => {
    let cancelled = false;
    estimateMemoryTasks(server, { selection, model_override: modelOverride })
      .then((result) => {
        if (!cancelled) setEstimate(result);
      })
      .catch((estimateError: unknown) => {
        if (!cancelled) setError(estimateError instanceof Error ? estimateError.message : String(estimateError));
      });
    return () => {
      cancelled = true;
    };
  }, [server, selection, modelOverride]);

  async function handleRun(): Promise<void> {
    setRunning(true);
    setError(null);
    try {
      const { count } = await runMemoryTasks(server, { selection, model_override: modelOverride });
      onQueued(count);
      dialogRef.current?.close();
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : String(runError));
      setRunning(false);
    }
  }

  const remaining = status ? remainingBudget(status) : null;
  const overBudget = estimate !== null && remaining?.usd != null && Number(estimate.cost_usd) > remaining.usd;

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      aria-labelledby="memory-run-title"
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-2xl border border-border bg-background p-0 text-foreground shadow-xl backdrop:bg-black/40"
    >
      <div className="space-y-4 p-5">
        <h2 id="memory-run-title" className="text-lg font-semibold tracking-tight">{t("title")}</h2>

        {estimate === null && error === null ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("estimating")}
          </div>
        ) : estimate ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-sm">
            <dt className="text-muted-foreground">{t("tasks")}</dt>
            <dd className="tabular-nums">{estimate.task_count.toLocaleString(locale)}</dd>
            <dt className="text-muted-foreground">{t("inputTokens")}</dt>
            <dd className="tabular-nums">{formatTokens(estimate.input_tokens, locale)}</dd>
            <dt className="text-muted-foreground">{t("cost")}</dt>
            <dd className="tabular-nums">
              ~{formatUsd(estimate.cost_usd, locale)}
              {estimate.unpriced_count > 0 ? (
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

        {overBudget ? <p className="text-sm text-amber-700 dark:text-amber-400">{t("overBudget")}</p> : null}

        <div className="space-y-1.5">
          <span className="text-xs font-medium text-muted-foreground">{t("model")}</span>
          <ModelPicker
            value={modelOverride}
            entries={models}
            onChange={(model) => {
              setModelOverride(model);
              setEstimate(null);
              setError(null);
            }}
            disabled={running}
            defaultLabel={t("roleDefault")}
            defaultDescription={status ? `memory_low: ${status.models.memory_low} · memory_high: ${status.models.memory_high}` : undefined}
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
            disabled={running || estimate === null || estimate.task_count === 0}
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
