"use client";

import { Check, Copy } from "lucide-react";
import {
  Children,
  cloneElement,
  isValidElement,
  useCallback,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
  type ReactElement,
  type ReactNode,
} from "react";

type MarkdownPreProps = ComponentPropsWithoutRef<"pre"> & { node?: unknown };

function readDataLanguage(props: Record<string, unknown>): string | undefined {
  const raw = props["data-language"] ?? props.dataLanguage;
  return typeof raw === "string" && raw.length > 0 ? raw : undefined;
}

function languageFromFenceCode(children: ReactNode): string | undefined {
  let out: string | undefined;
  Children.forEach(children, (c) => {
    if (out) return;
    if (isValidElement(c) && c.type === "code") {
      const cls = (c.props as { className?: string | string[] }).className;
      const s = Array.isArray(cls) ? cls.join(" ") : String(cls ?? "");
      const m = /\blanguage-(\S+)/.exec(s);
      if (m) out = m[1];
    }
  });
  return out;
}

/** Plain fenced code (sync Markdown fallback): split lines so CSS line numbers apply. */
function flattenIfOnlyStrings(node: ReactNode): string | null {
  if (node === null || node === undefined || node === false) return "";
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) {
    let acc = "";
    for (const x of node) {
      const f = flattenIfOnlyStrings(x);
      if (f === null) return null;
      acc += f;
    }
    return acc;
  }
  if (isValidElement(node)) return null;
  return null;
}

function wrapPlainFenceWithLineNumbers(children: ReactNode): ReactNode {
  const arr = Children.toArray(children);
  if (arr.length !== 1 || !isValidElement(arr[0]) || arr[0].type !== "code") {
    return children;
  }
  const codeEl = arr[0] as ReactElement<{
    children?: ReactNode;
    className?: string;
    [key: string]: unknown;
  }>;
  const p = codeEl.props;
  if (p["data-line-numbers"] != null) return children;

  const text = flattenIfOnlyStrings(p.children);
  if (text === null) return children;

  const raw = text.replace(/\n$/, "");
  const lines = raw.length === 0 ? [""] : raw.split("\n");
  const lined = lines.map((line, i) => (
    <span key={i} data-line="">
      {i > 0 ? "\n" : null}
      {line}
    </span>
  ));

  const restProps = { ...p };
  delete (restProps as { children?: ReactNode }).children;
  delete (restProps as { node?: unknown }).node;
  const prevCls = p.className;
  const className = [prevCls, "md-plain-fence-code"].filter(Boolean).join(" ");

  return cloneElement(codeEl, {
    ...restProps,
    className,
    "data-line-numbers": "",
    children: lined,
  });
}

export function MarkdownPre({ children, ...props }: MarkdownPreProps) {
  const preRef = useRef<HTMLPreElement>(null);
  const preProps = { ...props };
  delete (preProps as { node?: unknown }).node;
  const record = preProps as Record<string, unknown>;
  const lang = readDataLanguage(record) ?? languageFromFenceCode(children);

  const [copied, setCopied] = useState(false);
  const copy = useCallback(async () => {
    const el = preRef.current;
    const code = el?.querySelector("code");
    const text = (code?.textContent ?? el?.textContent ?? "").replace(
      /\n$/,
      "",
    );
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard may be denied; avoid throwing in UI */
    }
  }, []);

  return (
    <div className="md-code-block-shell not-prose">
      <div className="md-code-block-toolbar">
        {lang ? (
          <span className="md-code-block-lang" title={lang}>
            {lang}
          </span>
        ) : (
          <span className="min-w-0 shrink" aria-hidden />
        )}
        <button
          type="button"
          className="md-code-block-copy"
          aria-label={copied ? "Copied" : "Copy code"}
          title="Copy"
          onClick={() => void copy()}
        >
          {copied ? (
            <Check className="size-3.5" strokeWidth={2} />
          ) : (
            <Copy className="size-3.5" strokeWidth={2} />
          )}
        </button>
      </div>
      <pre ref={preRef} {...preProps}>
        {wrapPlainFenceWithLineNumbers(children)}
      </pre>
    </div>
  );
}
