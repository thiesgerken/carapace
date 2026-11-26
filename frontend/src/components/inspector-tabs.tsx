"use client";

import { useTranslations } from "next-intl";
import { INSPECTOR_TABS, type InspectorTab } from "@/lib/inspector-tabs";
import { handleTabListKeyDown } from "@/lib/tabs";
import { cn } from "@/lib/utils";

/** The inspector's tab strip; the panel below it shows the selected tab's sections. */
export function InspectorTabs({ value, onChange }: { value: InspectorTab; onChange: (tab: InspectorTab) => void }) {
  const t = useTranslations("chatView.inspector");
  return (
    <div
      role="tablist"
      aria-label={t("tabsLabel")}
      onKeyDown={handleTabListKeyDown}
      className="flex rounded-lg bg-muted p-0.5 text-xs font-medium"
    >
      {INSPECTOR_TABS.map((tab) => (
        <button
          key={tab}
          type="button"
          role="tab"
          aria-selected={tab === value}
          tabIndex={tab === value ? 0 : -1}
          onClick={() => onChange(tab)}
          className={cn(
            "min-w-0 flex-auto truncate rounded-md px-2 py-1.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            tab === value ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {t(`tabs.${tab}`)}
        </button>
      ))}
    </div>
  );
}
