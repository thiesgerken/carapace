"use client";

import { Maximize2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { artifactViewerHref } from "@/lib/artifacts";

export function ArtifactViewerLink({ slug, snapshot = false }: { slug: string; snapshot?: boolean }) {
  const t = useTranslations("artifacts");
  return (
    <Link
      href={artifactViewerHref(slug)}
      className="inline-flex items-center gap-1.5 rounded px-2 py-1.5 text-xs font-medium text-teal-600 hover:bg-teal-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:text-teal-400"
    >
      <Maximize2 className="h-3.5 w-3.5 shrink-0" />
      {t(snapshot ? "openLive" : "fullScreen")}
    </Link>
  );
}
