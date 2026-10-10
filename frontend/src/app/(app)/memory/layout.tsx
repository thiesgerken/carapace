"use client";

import { useEffect, type ReactNode } from "react";
import Link from "next/link";
import { useSelectedLayoutSegment } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAppShell } from "@/components/app-shell-context";
import { MemoryStatusProvider, MemoryStatusStrip } from "@/components/memory-status";
import { useBrand } from "@/hooks/use-brand";
import { MEMORY_TABS, type MemoryTab } from "@/lib/memory-tabs";
import { handleTabListKeyDown, tabbedPageClassName, tabLinkClassName } from "@/lib/tabs";

export default function MemoryLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("memory");
  const { server } = useAppShell();
  const { name: brand } = useBrand();
  const segment = useSelectedLayoutSegment() as MemoryTab | null;
  const activeTab: MemoryTab = segment ?? "timeline";

  useEffect(() => {
    document.title = `${t("title")} • ${brand}`;
  }, [brand, t]);

  return (
    <MemoryStatusProvider server={server}>
      <div className={tabbedPageClassName}>
        <div className="px-5 pt-4 sm:px-6">
          <h1 className="pb-4 text-2xl font-semibold tracking-tight">{t("title")}</h1>

          <MemoryStatusStrip />

          <div
            role="tablist"
            onKeyDown={handleTabListKeyDown}
            aria-label={t("sections")}
            className="flex items-end gap-1 border-b border-border/80"
          >
            {MEMORY_TABS.map((tab) => {
              const selected = activeTab === tab;
              return (
                <Link
                  key={tab}
                  id={`memory-tab-${tab}`}
                  href={`/memory/${tab}`}
                  role="tab"
                  aria-selected={selected}
                  aria-controls={`memory-panel-${tab}`}
                  tabIndex={selected ? 0 : -1}
                  className={tabLinkClassName(selected)}
                >
                  {t(`tabs.${tab}`)}
                </Link>
              );
            })}
          </div>
        </div>

        {children}
      </div>
    </MemoryStatusProvider>
  );
}
