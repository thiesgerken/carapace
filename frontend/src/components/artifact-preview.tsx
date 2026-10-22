"use client";

import { Code, ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

const ARTIFACT_SANDBOX = "allow-scripts";

export function ArtifactPreview({
  src,
  sourceUrl,
  title,
  fullScreen = false,
  toolbar,
}: {
  src: string;
  sourceUrl: string;
  title: string;
  fullScreen?: boolean;
  toolbar?: ReactNode;
}) {
  const t = useTranslations("artifacts");
  const [showSource, setShowSource] = useState(false);
  const [source, setSource] = useState<{ url: string; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!showSource || source?.url === sourceUrl) return;
    const controller = new AbortController();
    async function loadSource() {
      try {
        const response = await fetch(sourceUrl, { signal: controller.signal });
        if (!response.ok) throw new Error(`Failed to load artifact source: ${response.status}`);
        const text = await response.text();
        if (!controller.signal.aborted) {
          setSource({ url: sourceUrl, text });
          setError(null);
        }
      } catch {
        if (!controller.signal.aborted) {
          setError(t("sourceError"));
        }
      }
    }
    void loadSource();
    return () => controller.abort();
  }, [showSource, source?.url, sourceUrl, t]);

  return (
    <section className={cn("overflow-hidden", fullScreen ? "flex min-h-0 flex-1 flex-col" : "rounded-lg border border-border")}>
      <div className="flex flex-wrap items-center justify-end gap-2 border-b border-border bg-muted/25 px-3 py-2 text-xs">
        {toolbar}
        <button
          type="button"
          aria-pressed={showSource}
          onClick={() => setShowSource((shown) => !shown)}
          className={cn("inline-flex items-center gap-1.5 rounded px-2 py-1 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", fullScreen && "min-h-10")}
        >
          <Code className="h-3.5 w-3.5" />
          {t(showSource ? "preview" : "source")}
        </button>
        {!fullScreen && (
          <a
            href={src}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded px-2 py-1 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            {t("openInNewTab")}
          </a>
        )}
      </div>
      {showSource ? (
        error ? <p role="alert" className="p-4 text-sm text-destructive">{error}</p> : (
          <pre className={cn("overflow-auto bg-muted/20 p-4 font-mono text-xs leading-relaxed", fullScreen ? "min-h-0 flex-1" : "h-[32rem]")}>
            {source?.url === sourceUrl ? source.text : t("loading")}
          </pre>
        )
      ) : (
        <iframe src={src} title={title} sandbox={ARTIFACT_SANDBOX} className={cn("w-full border-0", fullScreen ? "min-h-0 flex-1" : "h-[32rem]")} />
      )}
    </section>
  );
}
