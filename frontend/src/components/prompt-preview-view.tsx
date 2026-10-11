"use client";

import { useEffect, useState, type ReactNode } from "react";
import { ChevronRight, Loader2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { MarkdownContent } from "@/components/markdown-content";
import { getPromptPreview } from "@/lib/api";
import { fencedCodeBlock } from "@/lib/sandbox-read";
import { PROMPT_ROLES, type PromptPreview, type PromptRole, type PromptSection } from "@/lib/types";
import { cn } from "@/lib/utils";

type View = "rendered" | "raw";

const pillClassName = (selected: boolean): string => cn(
  "rounded-full border px-3 py-1.5 text-sm transition-colors",
  selected
    ? "border-[#236b86]/60 bg-[#236b86]/10 text-foreground dark:border-sky-400/50 dark:bg-sky-400/10"
    : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
);

/** The chat's context gauge palette; sections take colours in order, repeating past six. */
const SECTION_COLORS = ["bg-sky-500/80", "bg-emerald-500/80", "bg-violet-500/80", "bg-amber-500/80", "bg-orange-500/80", "bg-rose-500/80"];
const sectionColor = (index: number): string => SECTION_COLORS[index % SECTION_COLORS.length];
const sectionElementId = (key: string): string => `prompt-section-${key}`;

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
  const [view, setView] = useState<View>("rendered");
  const { preview, error } = usePromptPreview(server, role);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div role="radiogroup" aria-label={t("role")} className="flex flex-wrap gap-1.5">
            {PROMPT_ROLES.map((value) => (
              <button key={value} type="button" role="radio" aria-checked={value === role} onClick={() => setRole(value)} className={pillClassName(value === role)}>
                {t(`roles.${value}`)}
              </button>
            ))}
          </div>
          <div role="radiogroup" aria-label={t("view")} className="flex gap-1.5">
            {(["rendered", "raw"] as const).map((value) => (
              <button key={value} type="button" role="radio" aria-checked={value === view} onClick={() => setView(value)} className={pillClassName(value === view)}>
                {t(`views.${value}`)}
              </button>
            ))}
          </div>
        </div>

        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : preview === null ? (
          <Loader2 className="mx-auto mt-8 h-5 w-5 animate-spin text-muted-foreground" />
        ) : (
          <PreviewBody preview={preview} view={view} />
        )}
      </div>
    </div>
  );
}

function PreviewBody({ preview, view }: { preview: PromptPreview; view: View }) {
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
        <SectionShareBar preview={preview} />
      </div>

      <div className="space-y-2">
        {preview.sections.map((section, index) => (
          <div key={section.key} className="space-y-2">
            <SectionBlock section={section} color={sectionColor(index)} view={view} />
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

/** Each section's share of the prompt; a segment expands its section and scrolls to it. */
function SectionShareBar({ preview }: { preview: PromptPreview }) {
  const t = useTranslations("promptPreview");
  const format = useFormatter();
  const [active, setActive] = useState<PromptSection | null>(null);
  const { sections, cacheable_until: cacheableUntil } = preview;
  const sum = sections.reduce((total, section) => total + section.tokens, 0);
  const cacheEndPercent = cacheableUntil === null || sum === 0
    ? null
    : (sections.slice(0, cacheableUntil + 1).reduce((total, section) => total + section.tokens, 0) / sum) * 100;

  function describe(section: PromptSection): string {
    const share = format.number(section.tokens / preview.total_tokens, { style: "percent", maximumFractionDigits: 1 });
    return `${section.title} · ${t("tokens", { count: section.tokens })} · ${share}`;
  }

  function reveal(section: PromptSection): void {
    const details = document.getElementById(sectionElementId(section.key)) as HTMLDetailsElement | null;
    if (details === null) return;
    details.open = true;
    details.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  return (
    <div className="basis-full space-y-1.5 border-t border-border/60 pt-3">
      <div className="relative">
        <div className="flex h-3 gap-0.5 overflow-hidden rounded-full bg-muted">
          {sections.map((section, index) => (
            <button
              key={section.key}
              type="button"
              aria-label={describe(section)}
              onClick={() => reveal(section)}
              onMouseEnter={() => setActive(section)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(section)}
              onBlur={() => setActive(null)}
              style={{ flexGrow: section.tokens, flexBasis: 0 }}
              className={cn(sectionColor(index), "min-w-0 transition-opacity hover:opacity-80 focus-visible:opacity-80 focus-visible:outline-none")}
            />
          ))}
        </div>
        {cacheEndPercent !== null ? (
          <div
            title={t("cacheEnd")}
            className="pointer-events-none absolute -bottom-1 -top-1 w-0.5 -translate-x-1/2 rounded-full bg-[#236b86] dark:bg-sky-400"
            style={{ left: `${cacheEndPercent}%` }}
          />
        ) : null}
      </div>
      <div className="min-h-4 truncate text-xs text-muted-foreground">{active ? describe(active) : null}</div>
    </div>
  );
}

function SectionBlock({ section, color, view }: { section: PromptSection; color: string; view: View }) {
  const t = useTranslations("promptPreview");
  // Bodies mount on first open only, so Shiki never runs for sections nobody looks at.
  const [opened, setOpened] = useState(false);

  return (
    <details
      id={sectionElementId(section.key)}
      onToggle={(event) => event.currentTarget.open && setOpened(true)}
      className="group/section scroll-mt-4 rounded-2xl border border-border bg-background/88 shadow-sm"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 [&::-webkit-details-marker]:hidden">
        <ChevronRight aria-hidden="true" className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open/section:rotate-90" />
        <span aria-hidden="true" className={cn("h-2 w-2 shrink-0 rounded-full", color)} />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{section.title}</span>
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{t("tokens", { count: section.tokens })}</span>
      </summary>
      {opened ? <SectionText section={section} view={view} /> : null}
    </details>
  );
}

function SectionText({ section, view }: { section: PromptSection; view: View }) {
  const frameClassName = "max-h-[32rem] overflow-auto border-t border-border/60 px-4 py-3";
  // The tool definitions are JSON, not Markdown: highlighted in both views.
  if (section.key === "tools") {
    return <div className={frameClassName}><MarkdownContent content={fencedCodeBlock("json", section.text)} /></div>;
  }
  // Memory is distilled from past sessions, tool output included, so it is untrusted: rendering it
  // would turn a Markdown image in there into a live request to any host.
  if (view === "rendered" && section.key !== "memory") {
    return <div className={frameClassName}><MarkdownContent content={section.text} /></div>;
  }
  return <pre className={cn(frameClassName, "whitespace-pre-wrap break-words font-mono text-xs leading-relaxed")}>{section.text}</pre>;
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
