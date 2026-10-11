"use client";

import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { Check, Code, Copy, Download, Image as ImageIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { stripRemoteSvgImages } from "@/lib/remote-images";

type MermaidState = { svg: string } | { error: string } | null;

/* mermaid.render() removes any element already carrying the id it is given — including an
   SVG this component injected earlier — and reads back a temp container it appends to
   document.body. Two renders sharing an id therefore delete each other's work, so every
   invocation gets a fresh id and renders run one at a time. */
let renderQueue: Promise<unknown> = Promise.resolve();
let renderCount = 0;

export function MermaidDiagram({ code }: { code: string }) {
  const t = useTranslations("message.mermaid");
  const { resolvedTheme } = useTheme();
  const [state, setState] = useState<MermaidState>(null);
  const [showSource, setShowSource] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      if (cancelled) return;
      const mermaid = (await import("mermaid")).default;
      mermaid.initialize({
        startOnLoad: false,
        /** LLM output is untrusted: strict runs the SVG through DOMPurify and kills click callbacks. */
        securityLevel: "strict",
        /** Without this, a failed draw leaves its error graphic pinned to document.body. */
        suppressErrorRendering: true,
        theme: resolvedTheme === "dark" ? "dark" : "default",
      });

      /* While a reply streams in, the fence is incomplete and parse fails; stay on the
         source view instead of flashing an error until it becomes valid. */
      if (!(await mermaid.parse(code, { suppressErrors: true }))) {
        if (!cancelled) setState(null);
        return;
      }
      /* A newer render superseded this one — skip the layout work. */
      if (cancelled) return;

      const { svg } = await mermaid.render(`mermaid-${(renderCount += 1)}`, code);
      if (!cancelled) setState({ svg: stripRemoteSvgImages(svg) });
    };

    renderQueue = renderQueue.then(run).catch((error: unknown) => {
      if (!cancelled) {
        setState({ error: error instanceof Error ? error.message : String(error) });
      }
    });

    return () => {
      cancelled = true;
    };
  }, [code, resolvedTheme]);

  const svg = state && "svg" in state ? state.svg : null;
  const sourceShown = showSource || svg === null;

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(sourceShown ? code : (svg ?? code));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard may be denied; avoid throwing in UI */
    }
  }, [code, sourceShown, svg]);

  const download = useCallback(() => {
    if (!svg) return;
    const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "diagram.svg";
    document.body.append(link);
    link.click();
    link.remove();
    /* Revoking in the same tick aborts the download in Safari and Firefox. */
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }, [svg]);

  return (
    <div className="md-code-block-shell not-prose">
      <div className="md-code-block-toolbar">
        <span className="md-code-block-lang">mermaid</span>
        {svg ? (
          <>
            <button
              type="button"
              className="md-code-block-copy"
              aria-label={sourceShown ? t("showDiagram") : t("showSource")}
              title={sourceShown ? t("showDiagram") : t("showSource")}
              onClick={() => setShowSource((prev) => !prev)}
            >
              {sourceShown ? (
                <ImageIcon className="size-3.5" strokeWidth={2} />
              ) : (
                <Code className="size-3.5" strokeWidth={2} />
              )}
            </button>
            <button
              type="button"
              className="md-code-block-copy"
              aria-label={t("download")}
              title={t("download")}
              onClick={download}
            >
              <Download className="size-3.5" strokeWidth={2} />
            </button>
          </>
        ) : null}
        <button
          type="button"
          className="md-code-block-copy"
          aria-label={copyLabel(t, copied, sourceShown)}
          title={copyLabel(t, copied, sourceShown)}
          onClick={() => void copy()}
        >
          {copied ? (
            <Check className="size-3.5" strokeWidth={2} />
          ) : (
            <Copy className="size-3.5" strokeWidth={2} />
          )}
        </button>
      </div>
      {state && "error" in state ? (
        <p className="mermaid-error">{t("renderFailed", { error: state.error })}</p>
      ) : null}
      {sourceShown ? (
        <pre>
          <code>{code}</code>
        </pre>
      ) : (
        <div
          className="mermaid-diagram"
          /* mermaid sanitizes its own output at securityLevel "strict". */
          dangerouslySetInnerHTML={{ __html: svg ?? "" }}
        />
      )}
    </div>
  );
}

function copyLabel(
  t: (key: string) => string,
  copied: boolean,
  sourceShown: boolean,
): string {
  if (copied) return t("copied");
  return sourceShown ? t("copySource") : t("copySvg");
}
