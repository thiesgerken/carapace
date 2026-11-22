"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useCallback } from "react";

import { useKeyedFetch } from "@/hooks/use-keyed-fetch";
import { useNow } from "@/hooks/use-now";
import { getSessionArtifacts } from "@/lib/api";
import { artifactViewerHref } from "@/lib/artifacts";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/format-time";

/** The session artifacts, reloaded whenever *refreshKey* changes. Hidden while there are none. */
export function SessionArtifactsSection({ server, sessionId, refreshKey }: { server: string; sessionId: string; refreshKey: number }) {
  const t = useTranslations("chatView.artifacts");
  const tSidebar = useTranslations("sidebar");
  const locale = useLocale();
  const now = useNow(false);
  const load = useCallback(() => getSessionArtifacts(server, sessionId), [server, sessionId]);
  const key = `${server}\n${sessionId}\n${refreshKey}`;
  const outcome = useKeyedFetch(key, load);
  // A previous session's list must not show under this one while it loads.
  const current = outcome && outcome.key.startsWith(`${server}\n${sessionId}\n`) ? outcome : null;
  if (current === null || ("value" in current && current.value.length === 0)) return null;

  return (
    <section className="rounded-2xl border border-border/70 bg-background/90 p-3 shadow-sm">
      <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{t("title")}</div>
      {"error" in current ? (
        <p role="alert" className="mt-2 text-xs text-destructive">{t("loadError")}</p>
      ) : (
        <ul className="mt-2 space-y-1.5 text-xs">
          {current.value.map((artifact) => (
            <li key={artifact.slug} className="flex min-w-0 items-baseline justify-between gap-2">
              {artifact.exists ? (
                <Link
                  href={artifactViewerHref(artifact.slug)}
                  className="min-w-0 truncate rounded-sm font-medium text-foreground underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  title={artifact.title}
                >
                  {artifact.title}
                </Link>
              ) : (
                <span className="min-w-0 truncate text-muted-foreground line-through" title={t("deleted")}>
                  {artifact.title}
                </span>
              )}
              <span className="shrink-0 text-muted-foreground" title={formatAbsoluteTime(artifact.last_changed, locale)}>
                {t(artifact.change, { time: formatRelativeTime(artifact.last_changed, locale, now, tSidebar("time.justNow")) })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
