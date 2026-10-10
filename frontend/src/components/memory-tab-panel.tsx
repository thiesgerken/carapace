"use client";

import { useTranslations } from "next-intl";
import type { MemoryTab } from "@/lib/memory-tabs";

export function MemoryTabPanel({ tab }: { tab: MemoryTab }) {
  const t = useTranslations("memory");
  return (
    <div
      id={`memory-panel-${tab}`}
      role="tabpanel"
      aria-labelledby={`memory-tab-${tab}`}
      className="flex min-h-0 flex-1 flex-col items-center justify-center overflow-hidden bg-background/65 p-6 text-sm text-muted-foreground"
    >
      {t("comingSoon")}
    </div>
  );
}
