"use client";

import { ArrowLeft, FolderOpen } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { useAppShell } from "@/components/app-shell-context";
import { ArtifactPreview } from "@/components/artifact-preview";
import { ArtifactShareControls } from "@/components/artifact-share-controls";
import { knowledgeArtifactUrl, knowledgeRawUrl } from "@/lib/api";
import { artifactSlugFromPath } from "@/lib/artifacts";
import { knowledgeBrowseHref } from "@/lib/knowledge-links";

export default function ArtifactPage() {
  const { server } = useAppShell();
  const searchParams = useSearchParams();
  const router = useRouter();
  const t = useTranslations("artifacts");
  const slug = searchParams.get("slug");
  const path = `artifacts/${slug}/index.html`;

  if (!slug || artifactSlugFromPath(path) !== slug) {
    return <p role="alert" className="p-4 text-sm">{t("invalidSlug")}</p>;
  }

  const knowledgeHref = knowledgeBrowseHref(path);
  function back() {
    if (window.history.length > 1) router.back();
    else router.replace(knowledgeHref);
  }

  return (
    <ArtifactPreview
      key={`${server}:${slug}`}
      fullScreen
      src={knowledgeArtifactUrl(server, slug)}
      sourceUrl={knowledgeRawUrl(server, path)}
      title={slug}
      toolbar={
        <>
          <button
            type="button"
            onClick={back}
            className="inline-flex min-h-10 items-center gap-1.5 rounded px-2 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ArrowLeft className="h-4 w-4" />
            {t("back")}
          </button>
          <h1 className="mr-auto min-w-0 max-w-60 truncate text-base font-semibold" title={slug}>{slug}</h1>
          <ArtifactShareControls server={server} slug={slug} />
          <Link
            href={knowledgeHref}
            className="inline-flex min-h-10 items-center gap-1.5 rounded px-2 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <FolderOpen className="h-4 w-4" />
            {t("openKnowledge")}
          </Link>
        </>
      }
    />
  );
}
