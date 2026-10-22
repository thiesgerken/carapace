"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";
import { ArtifactToolbar, type LiveArtifact } from "@/components/artifact-toolbar";

const ARTIFACT_SANDBOX = "allow-scripts";

export function ArtifactPreview({
  src,
  sourceUrl,
  title,
  fullScreen = false,
  artifact,
  snapshot = false,
}: {
  src: string;
  sourceUrl: string;
  title: string;
  fullScreen?: boolean;
  artifact?: LiveArtifact;
  snapshot?: boolean;
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
      {!snapshot && <ArtifactToolbar artifact={artifact} title={title} src={src} fullScreen={fullScreen} showSource={showSource} onToggleSource={() => setShowSource((shown) => !shown)} />}
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
