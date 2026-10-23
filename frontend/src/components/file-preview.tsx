"use client";

import { useEffect, useState } from "react";
import { Download, File as FileIcon } from "lucide-react";
import { fetchSentFile, sentFileUrl } from "@/lib/api";
import { cn, formatBytes } from "@/lib/utils";
import { ArtifactPreview } from "@/components/artifact-preview";
import { ArtifactViewerLink } from "@/components/artifact-viewer-link";
import { sentArtifactSlug } from "@/lib/artifacts";

/** Renders a persisted file with its preview and download chip. */
export function FilePreview({
  fileId,
  name,
  path,
  mime,
  size,
  server,
  sessionId,
  className,
}: {
  fileId: string;
  name: string;
  path?: string;
  mime?: string;
  size?: number;
  server?: string;
  sessionId?: string;
  className?: string;
}) {
  const artifactSlug = sentArtifactSlug(path);
  // Keyed by fileId so a stale preview from a previous file is never shown while the
  // new one loads (the render guard below ignores any url whose key != current fileId).
  const [preview, setPreview] = useState<{ fileId: string; url: string } | null>(null);
  const isImage = (mime ?? "").startsWith("image/");
  const canFetch = server !== undefined && sessionId !== undefined;

  useEffect(() => {
    if (!isImage || !canFetch) return;
    let url: string | null = null;
    let cancelled = false;
    fetchSentFile(server, sessionId, fileId)
      .then((blob) => {
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setPreview({ fileId, url });
      })
      .catch(() => {
        /* fall back to the download chip below */
      });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [isImage, canFetch, server, sessionId, fileId]);

  const previewUrl = preview?.fileId === fileId ? preview.url : null;

  const downloadHref = canFetch
    ? sentFileUrl(server, sessionId, fileId, { download: true })
    : undefined;

  return (
    <div className={cn("rounded-md border border-border/40 bg-muted/25 p-2", className)}>
      {mime === "text/html" && canFetch && (
        <ArtifactPreview
          key={fileId}
          snapshot={artifactSlug !== null}
          src={sentFileUrl(server, sessionId, fileId, { artifact: true })}
          sourceUrl={sentFileUrl(server, sessionId, fileId)}
          title={name}
        />
      )}
      {isImage && previewUrl && (
        <a href={previewUrl} target="_blank" rel="noreferrer" className="block">
          {/* eslint-disable-next-line @next/next/no-img-element -- blob: object URL, next/image can't optimize it */}
          <img
            src={previewUrl}
            alt={name}
            className="max-h-80 w-auto max-w-full rounded"
          />
        </a>
      )}
      <div className="mt-1.5 flex items-center gap-2 first:mt-0">
        {artifactSlug !== null ? (
          <ArtifactViewerLink slug={artifactSlug} snapshot />
        ) : (
          <>
            <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="truncate font-medium text-foreground/85" title={path}>
              {name}
            </span>
            {size != null && (
              <span className="shrink-0 text-muted-foreground">{formatBytes(size)}</span>
            )}
          </>
        )}
        {downloadHref && (
          <a
            href={downloadHref}
            download={artifactSlug !== null ? `${artifactSlug}.html` : name}
            className="ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium text-teal-600 hover:bg-teal-500/10 dark:text-teal-400"
          >
            <Download className="h-3 w-3" />
            Download
          </a>
        )}
      </div>
    </div>
  );
}
