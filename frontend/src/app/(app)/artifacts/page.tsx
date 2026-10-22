"use client";

import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useAppShell } from "@/components/app-shell-context";
import { ArtifactPreview } from "@/components/artifact-preview";
import { browseKnowledge, knowledgeArtifactUrl, knowledgeRawUrl, type KnowledgeArtifact } from "@/lib/api";
import { artifactSlugFromPath } from "@/lib/artifacts";

function ArtifactViewer({ server, slug }: { server: string; slug: string }) {
  const t = useTranslations("artifacts");
  const [artifact, setArtifact] = useState<KnowledgeArtifact | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const result = await browseKnowledge(server, `artifacts/${slug}`);
        if (!result.artifact) throw new Error("Not an artifact");
        if (!cancelled) setArtifact(result.artifact);
      } catch {
        if (!cancelled) setError(true);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [server, slug]);

  useEffect(() => {
    if (artifact) document.title = artifact.title;
  }, [artifact]);

  if (error) return <p role="alert" className="p-4 text-sm text-destructive">{t("loadError")}</p>;
  if (!artifact) return <p className="p-4 text-sm">{t("loadingArtifact")}</p>;
  return <ArtifactPreview fullScreen src={knowledgeArtifactUrl(server, slug)} sourceUrl={knowledgeRawUrl(server, `artifacts/${slug}/index.html`)} title={artifact.title} artifact={{ server, slug }} />;
}

export default function ArtifactPage() {
  const { server } = useAppShell();
  const slug = useSearchParams().get("slug");
  const t = useTranslations("artifacts");
  if (!slug || artifactSlugFromPath(`artifacts/${slug}/index.html`) !== slug) {
    return <p role="alert" className="p-4 text-sm">{t("invalidSlug")}</p>;
  }
  return <ArtifactViewer key={`${server}:${slug}`} server={server} slug={slug} />;
}
