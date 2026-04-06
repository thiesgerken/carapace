"use client";

import { useMemo } from "react";
import Markdown, { MarkdownHooks } from "react-markdown";
import rehypePrettyCode, {
  type Options as RehypePrettyCodeOptions,
} from "rehype-pretty-code";
import remarkGfm from "remark-gfm";
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

export function MarkdownContent({ content }: { content: string }) {
  const remarkPlugins = useMemo(() => [remarkGfm], []);
  const rehypePlugins = useMemo((): PluggableList => {
    return [[rehypePrettyCode, PRETTY_CODE_OPTIONS]];
  }, []);

  const components = useMemo(() => ({ pre: MarkdownPre }), []);

  return (
    <div className="prose">
      <MarkdownHooks
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={components}
        fallback={
          <Markdown remarkPlugins={remarkPlugins} components={components}>
            {content}
          </Markdown>
        }
      >
        {content}
      </MarkdownHooks>
    </div>
  );
}
