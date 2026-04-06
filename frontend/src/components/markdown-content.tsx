"use client";

import { useMemo } from "react";
import Markdown, { MarkdownHooks } from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypePrettyCode, {
  type Options as RehypePrettyCodeOptions,
} from "rehype-pretty-code";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { PluggableList } from "unified";

import { MarkdownPre } from "./markdown-code-pre";

const PRETTY_CODE_OPTIONS: RehypePrettyCodeOptions = {
  theme: {
    light: "github-light",
    dark: "github-dark-dimmed",
  },
  keepBackground: false,
  filterMetaString: (meta) => {
    const m = meta.trim();
    if (/\bshowLineNumbers\b/.test(m)) return meta;
    return m ? `${m} showLineNumbers` : "showLineNumbers";
  },
};

const KATEX_OPTIONS = { strict: "ignore" as const };

export function MarkdownContent({ content }: { content: string }) {
  const remarkPlugins = useMemo(() => [remarkGfm, remarkMath], []);
  const rehypePluginsAsync = useMemo((): PluggableList => {
    return [
      [rehypePrettyCode, PRETTY_CODE_OPTIONS],
      [rehypeKatex, KATEX_OPTIONS],
    ];
  }, []);
  /** Sync `Markdown` cannot run `rehype-pretty-code` (Shiki is async). */
  const rehypePluginsFallback = useMemo((): PluggableList => {
    return [[rehypeKatex, KATEX_OPTIONS]];
  }, []);

  const components = useMemo(() => ({ pre: MarkdownPre }), []);

  return (
    <div className="prose">
      <MarkdownHooks
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePluginsAsync}
        components={components}
        fallback={
          <Markdown
            remarkPlugins={remarkPlugins}
            rehypePlugins={rehypePluginsFallback}
            components={components}
          >
            {content}
          </Markdown>
        }
      >
        {content}
      </MarkdownHooks>
    </div>
  );
}
