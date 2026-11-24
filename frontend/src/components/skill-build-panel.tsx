"use client";

import { CircleAlert, CircleCheck, CircleDashed, Hammer, Loader2, RotateCw, Terminal } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import { browseKnowledge, retrySkillBuild, type KnowledgeSkillBuild, type SkillBuildState } from "@/lib/api";

const POLL_MS = 3000;

const STATE_STYLE: Record<SkillBuildState, { icon: ReactNode; cls: string }> = {
  building: { icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />, cls: "text-muted-foreground" },
  succeeded: { icon: <CircleCheck className="h-3.5 w-3.5" />, cls: "text-emerald-600 dark:text-emerald-400" },
  failed: { icon: <CircleAlert className="h-3.5 w-3.5" />, cls: "text-destructive" },
  unavailable: { icon: <CircleDashed className="h-3.5 w-3.5" />, cls: "text-amber-600 dark:text-amber-400" },
};

/**
 * The build of a flake skill at HEAD: state, commands, and for a failure the log and a retry.
 * Owns its state after mounting; key it by path and tree so a new head starts it fresh.
 */
export function SkillBuildPanel({ server, skill, initial }: { server: string; skill: string; initial: KnowledgeSkillBuild }) {
  const t = useTranslations("knowledge.skill.build");
  const [build, setBuild] = useState(initial);
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A build takes seconds to minutes; follow it until it settles.
  useEffect(() => {
    if (build.state !== "building") return;
    const timer = window.setTimeout(async () => {
      try {
        const listing = await browseKnowledge(server, `skills/${skill}`);
        if (listing.type === "dir" && listing.build) setBuild(listing.build);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [build, server, skill]);

  async function retry() {
    setRetrying(true);
    setError(null);
    try {
      setBuild(await retrySkillBuild(server, skill));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRetrying(false);
    }
  }

  const style = STATE_STYLE[build.state];
  const commands = Object.entries(build.commands);
  return (
    <section className="rounded-lg border border-border bg-muted/30 p-4 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          <Hammer className="h-3.5 w-3.5" />
          {t("title")}
        </h2>
        <span className={`inline-flex items-center gap-1 font-medium ${style.cls}`}>
          {style.icon}
          {t(`state.${build.state}`)}
        </span>
        <code className="font-mono text-xs text-muted-foreground" title={t("tree")}>{build.tree.slice(0, 12)}</code>
        {build.state === "failed" ? (
          <button
            type="button"
            onClick={retry}
            disabled={retrying}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-medium transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
          >
            {retrying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCw className="h-3.5 w-3.5" />}
            {t("retry")}
          </button>
        ) : null}
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground">{t(`hint.${build.state}`)}</p>

      {build.log_tail && build.state !== "succeeded" ? (
        <details className="mt-3 text-xs" open={build.state === "failed"}>
          <summary className="cursor-pointer text-muted-foreground transition-colors hover:text-foreground">{t("log")}</summary>
          <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-2 font-mono">
            {build.log_tail}
          </pre>
        </details>
      ) : null}

      {commands.length ? (
        <div className="mt-3 flex flex-col gap-2 border-t border-border/70 pt-3">
          {commands.map(([name, command]) => (
            <div key={name} className="flex min-w-0 items-start gap-2">
              <Terminal className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <div className="flex min-w-0 flex-col gap-0.5">
                <code className="break-all font-mono text-xs font-semibold">{name}</code>
                <span className="break-words text-xs text-muted-foreground">{command.description}</span>
                {command.needs.domains.length ? (
                  <span className="break-all font-mono text-[11px] text-muted-foreground">
                    {t("needsDomains", { domains: command.needs.domains.join(", ") })}
                  </span>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {error ? <p className="mt-2 text-xs text-destructive">{error}</p> : null}
    </section>
  );
}
