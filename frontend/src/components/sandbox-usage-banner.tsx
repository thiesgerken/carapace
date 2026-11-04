"use client";

import { CircleAlert, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import type { SandboxUsage } from "@/lib/types";
import { cn } from "@/lib/utils";

const bannerClassName = "flex items-start gap-2 rounded-lg border px-3 py-2 text-xs leading-snug";

export function SandboxUsageBanner({ usage }: { usage: SandboxUsage | null }) {
  const t = useTranslations("sidebar.sandboxUsage");
  if (!usage) return null;

  const { count, warn_at: warnAt, max } = usage;
  if (max > 0 && count >= max) {
    return (
      <div role="alert" className={cn(bannerClassName, "border-destructive/40 bg-destructive/10 text-destructive")}>
        <CircleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
        <span>{t("limitReached", { count, max })}</span>
      </div>
    );
  }
  if (warnAt > 0 && count >= warnAt) {
    return (
      <div
        role="status"
        className={cn(bannerClassName, "border-amber-500/50 bg-amber-500/10 text-amber-800 dark:text-amber-300")}
      >
        <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
        <span>
          {max > 0 ? t("warning", { count, warnAt, max }) : t("warningUnlimited", { count, warnAt })}
        </span>
      </div>
    );
  }
  return null;
}
