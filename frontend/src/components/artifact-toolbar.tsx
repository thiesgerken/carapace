"use client";

import { ArrowLeft, Code, ExternalLink, FolderOpen } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { ArtifactShareControls } from "@/components/artifact-share-controls";
import { ArtifactViewerLink } from "@/components/artifact-viewer-link";
import type { KnowledgeArtifact } from "@/lib/api";
import { knowledgeBrowseHref } from "@/lib/knowledge-links";

export interface LiveArtifact extends Pick<KnowledgeArtifact, "slug" | "created_in" | "updated_in"> {
  server: string;
}

export function ArtifactToolbar({ artifact, title, src, fullScreen, showSource, onToggleSource }: {
  artifact?: LiveArtifact;
  title: string;
  src: string;
  fullScreen: boolean;
  showSource: boolean;
  onToggleSource: () => void;
}) {
  const t = useTranslations("artifacts");
  const knowledgeHref = artifact ? knowledgeBrowseHref(`artifacts/${artifact.slug}`) : null;
  const actionClass = "inline-flex min-h-10 items-center gap-1.5 rounded px-2 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

  function back() {
    if (window.history.length > 1) window.history.back();
    else if (knowledgeHref) window.location.assign(knowledgeHref);
  }

  return (
    <div className="flex flex-wrap items-center justify-end gap-2 border-b border-border bg-muted/25 px-3 py-2 text-xs">
      {fullScreen && <button type="button" onClick={back} className={actionClass}><ArrowLeft className="h-4 w-4" />{t("back")}</button>}
      {artifact && (
        <div className="mr-auto min-w-0">
          <h1 className="max-w-72 truncate text-base font-semibold" title={title}>{title}</h1>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-muted-foreground">
            {(["created_in", "updated_in"] as const).map(kind => {
              const session = artifact[kind];
              if (!session) return null;
              return (
                <span key={kind} className="inline-flex min-w-0 items-baseline gap-1">
                  <span className="shrink-0">{t(kind === "created_in" ? "createdIn" : "updatedIn")}</span>
                  {session.title ? (
                    <Link href={`/?session=${encodeURIComponent(session.session_id)}`} title={session.title} className="min-w-0 max-w-60 truncate rounded-sm underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                      {session.title}
                    </Link>
                  ) : <span className="min-w-0 truncate">{session.session_id}</span>}
                </span>
              );
            })}
          </div>
        </div>
      )}
      {artifact && <ArtifactShareControls server={artifact.server} slug={artifact.slug} />}
      {artifact && !fullScreen && <ArtifactViewerLink slug={artifact.slug} />}
      <button type="button" aria-pressed={showSource} onClick={onToggleSource} className={actionClass}>
        <Code className="h-3.5 w-3.5" />{t(showSource ? "preview" : "source")}
      </button>
      <a href={src} target="_blank" rel="noreferrer" className={actionClass}>
        <ExternalLink className="h-3.5 w-3.5" />{t("openInNewTab")}
      </a>
      {fullScreen && knowledgeHref && <Link href={knowledgeHref} className={actionClass}><FolderOpen className="h-4 w-4" />{t("openKnowledge")}</Link>}
    </div>
  );
}
