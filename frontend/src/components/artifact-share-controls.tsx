"use client";

import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { SwitchRow } from "@/components/switch-row";
import { getArtifactShare, setArtifactShared, type ArtifactShareState } from "@/lib/api";

export function ArtifactShareControls({ server, slug }: { server: string; slug: string }) {
  const t = useTranslations("artifacts.sharing");
  const [share, setShare] = useState<ArtifactShareState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const state = await getArtifactShare(server, slug);
        if (!cancelled) setShare(state);
      } catch {
        if (!cancelled) setError(t("loadError"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [server, slug, t]);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  async function toggle(shared: boolean): Promise<void> {
    if (shared && !window.confirm(t("confirm"))) return;
    setSaving(true);
    setError(null);
    try {
      setShare(await setArtifactShared(server, slug, shared));
      setCopied(false);
    } catch {
      setError(t("updateError"));
    } finally {
      setSaving(false);
    }
  }

  const publicUrl = share?.url ? new URL(share.url, server).href : null;

  async function copy(): Promise<void> {
    if (publicUrl === null) return;
    try {
      await navigator.clipboard.writeText(publicUrl);
      setCopied(true);
    } catch {
      setError(t("copyError"));
    }
  }

  return (
    <section className="space-y-3 rounded-xl border border-border bg-muted/20 p-3">
      <SwitchRow
        checked={publicUrl !== null}
        disabled={loading || saving || share === null}
        label={t("label")}
        description={loading ? t("loading") : t("description")}
        onCheckedChange={(shared) => void toggle(shared)}
      />
      {publicUrl !== null && (
        <div className="flex items-start gap-2 rounded-lg border border-border bg-background px-3 py-2">
          <a href={publicUrl} target="_blank" rel="noreferrer" className="min-w-0 flex-1 break-all text-xs text-teal-600 underline-offset-2 hover:underline dark:text-teal-400">
            {publicUrl}
          </a>
          <button
            type="button"
            onClick={() => void copy()}
            title={t(copied ? "copied" : "copy")}
            aria-label={t(copied ? "copied" : "copy")}
            className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          </button>
        </div>
      )}
      {error !== null && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </section>
  );
}
