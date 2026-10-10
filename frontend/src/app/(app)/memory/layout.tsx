"use client";

import { useEffect, type ReactNode } from "react";
import Link from "next/link";
import { useSelectedLayoutSegment } from "next/navigation";
import { useTranslations } from "next-intl";
import { useBrand } from "@/hooks/use-brand";
import { MEMORY_TABS, type MemoryTab } from "@/lib/memory-tabs";
import { tabbedPageClassName, tabLinkClassName } from "@/lib/tab-styles";

export default function MemoryLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("memory");
  const { name: brand } = useBrand();
  const segment = useSelectedLayoutSegment() as MemoryTab | null;
  const activeTab: MemoryTab = segment ?? "timeline";

  useEffect(() => {
    document.title = `${t("title")} • ${brand}`;
  }, [brand, t]);

  return (
    <div className={tabbedPageClassName}>
      <div className="px-5 pt-4 sm:px-6">
        <h1 className="pb-4 text-2xl font-semibold tracking-tight">{t("title")}</h1>

        {/* ponytail: placeholder until the status API lands (auto mode, budget gauges, queue counts). */}
        <div className="mb-4 rounded-lg border border-dashed border-border/80 px-4 py-3 text-xs text-muted-foreground">
          {t("statusPlaceholder")}
        </div>

        <div
          role="tablist"
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
  );
}
