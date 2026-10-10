"use client";

import { useAppShell } from "@/components/app-shell-context";
import { MemoryFactsView } from "@/components/memory-facts-view";
import { MemorySessionsView } from "@/components/memory-sessions-view";
import { MemoryTasksView } from "@/components/memory-tasks-view";
import { MemoryTimelineView } from "@/components/memory-timeline-view";
import type { MemoryTab } from "@/lib/memory-tabs";

function MemoryTabContent({ tab, server, token }: { tab: MemoryTab; server: string; token: string }) {
  switch (tab) {
    case "timeline":
      return <MemoryTimelineView server={server} token={token} />;
    case "sessions":
      return <MemorySessionsView server={server} token={token} />;
    case "facts":
      return <MemoryFactsView server={server} />;
    case "tasks":
      return <MemoryTasksView server={server} token={token} />;
  }
}

export function MemoryTabPanel({ tab }: { tab: MemoryTab }) {
  const { server, token } = useAppShell();
  return (
    <div
      id={`memory-panel-${tab}`}
      role="tabpanel"
      aria-labelledby={`memory-tab-${tab}`}
      className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background/65"
    >
      <MemoryTabContent tab={tab} server={server} token={token} />
    </div>
  );
}
