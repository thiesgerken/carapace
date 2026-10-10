"use client";

import { useTranslations } from "next-intl";
import { useAppShell } from "@/components/app-shell-context";
import { MemorySessionsView } from "@/components/memory-sessions-view";
import { MemoryTasksView } from "@/components/memory-tasks-view";
import { MemoryTimelineView } from "@/components/memory-timeline-view";
import type { MemoryTab } from "@/lib/memory-tabs";

export function MemoryTabPanel({ tab }: { tab: MemoryTab }) {
  const t = useTranslations("memory");
  const { server, token } = useAppShell();
  return (
    <div
      id={`memory-panel-${tab}`}
      role="tabpanel"
      aria-labelledby={`memory-tab-${tab}`}
      className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background/65"
    >
      {tab === "tasks" ? (
        <MemoryTasksView server={server} token={token} />
      ) : tab === "sessions" ? (
        <MemorySessionsView server={server} token={token} />
      ) : tab === "timeline" ? (
        <MemoryTimelineView server={server} token={token} />
      ) : (
        <div className="flex flex-1 items-center justify-center p-6 text-sm text-muted-foreground">{t("comingSoon")}</div>
      )}
    </div>
  );
}
