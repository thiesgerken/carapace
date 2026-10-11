"use client";

import { useEffect, useState, type ReactNode } from "react";
import { ChevronRight, Loader2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { getPromptPreview } from "@/lib/api";
import { PROMPT_ROLES, type PromptPreview, type PromptRole } from "@/lib/types";
import { cn } from "@/lib/utils";

type Outcome = { role: PromptRole; preview: PromptPreview } | { role: PromptRole; error: string };

function usePromptPreview(server: string, role: PromptRole): { preview: PromptPreview | null; error: string | null } {
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  useEffect(() => {
    let cancelled = false;
    getPromptPreview(server, role)
      .then((preview) => {
        if (!cancelled) setOutcome({ role, preview });
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setOutcome({ role, error: loadError instanceof Error ? loadError.message : String(loadError) });
      });
    return () => {
      cancelled = true;
    };
  }, [server, role]);

  // An outcome for another role reads as loading.
  if (outcome === null || outcome.role !== role) return { preview: null, error: null };
  return "error" in outcome ? { preview: null, error: outcome.error } : { preview: outcome.preview, error: null };
}

/** The full system prompt each role's model gets, section by section, so its size and cache boundary are visible. */
export function PromptPreviewView({ server }: { server: string }) {
  const t = useTranslations("promptPreview");
  const [role, setRole] = useState<PromptRole>("agent");
  const { preview, error } = usePromptPreview(server, role);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
        <div role="radiogroup" aria-label={t("role")} className="flex flex-wrap gap-1.5">
          {PROMPT_ROLES.map((value) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={value === role}
              onClick={() => setRole(value)}
              className={cn(
                "rounded-full border px-3 py-1.5 text-sm transition-colors",
                value === role
                  ? "border-[#236b86]/60 bg-[#236b86]/10 text-foreground dark:border-sky-400/50 dark:bg-sky-400/10"
                  : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {t(`roles.${value}`)}
            </button>
          ))}
        </div>

        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : preview === null ? (
          <Loader2 className="mx-auto mt-8 h-5 w-5 animate-spin text-muted-foreground" />
        ) : (
          <PreviewBody preview={preview} />
        )}
      </div>
    </div>
  );
}

function PreviewBody({ preview }: { preview: PromptPreview }) {
  const t = useTranslations("promptPreview");
  const format = useFormatter();

  return (
    <>
      <div className="flex flex-wrap items-start gap-x-8 gap-y-3 rounded-2xl border border-border bg-background/88 p-4 shadow-sm sm:p-5">
        <Stat label={t("model")} value={<span className="font-mono">{preview.model}</span>} />
        <Stat label={t("totalTokens")} value={<span className="tabular-nums">{format.number(preview.total_tokens)}</span>} />
        {preview.memory_budget_tokens !== null && preview.memory_used_tokens !== null ? (
          <MemoryBudget budget={preview.memory_budget_tokens} used={preview.memory_used_tokens} />
        ) : null}
      </div>

      <div className="space-y-2">
        {preview.sections.map((section, index) => (
          <div key={section.key} className="space-y-2">
            <details className="group/section rounded-2xl border border-border bg-background/88 shadow-sm">
              <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 [&::-webkit-details-marker]:hidden">
                <ChevronRight aria-hidden="true" className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open/section:rotate-90" />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{section.title}</span>
                <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{t("tokens", { count: section.tokens })}</span>
              </summary>
              <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words border-t border-border/60 px-4 py-3 font-mono text-xs leading-relaxed">{section.text}</pre>
            </details>
            {index === preview.cacheable_until ? (
              <div role="separator" className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.12em] text-[#236b86] dark:text-sky-400">
                <span className="h-px flex-1 border-t border-dashed border-current" />
                {t("cacheEnd")}
                <span className="h-px flex-1 border-t border-dashed border-current" />
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </>
  );
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="min-w-0 space-y-1">
      <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{label}</div>
      <div className="truncate text-sm">{value}</div>
    </div>
  );
}

function MemoryBudget({ budget, used }: { budget: number; used: number }) {
  const t = useTranslations("promptPreview");
  const format = useFormatter();
  return (
    <div className="min-w-48 flex-1 space-y-1">
      <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{t("memoryBudget")}</div>
      {budget === 0 ? (
        <div className="text-sm text-muted-foreground">{t("memoryOff")}</div>
      ) : (
        <>
          <div className="text-sm tabular-nums">{format.number(used)} / {format.number(budget)}</div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted" role="meter" aria-valuemin={0} aria-valuemax={budget} aria-valuenow={used}>
            <div className="h-full rounded-full bg-[#236b86] dark:bg-sky-400" style={{ width: `${Math.min(100, (used / budget) * 100)}%` }} />
          </div>
        </>
      )}
    </div>
  );
}
