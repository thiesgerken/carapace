"use client";

import { useMemo } from "react";
import Markdown, { MarkdownHooks, type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypePrettyCode, {
  type Options as RehypePrettyCodeOptions,
} from "rehype-pretty-code";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { PluggableList } from "unified";

import { splitEmojiText } from "@/lib/emoji";
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
const EMOJI_SKIP_TAGS = new Set([
  "code",
  "pre",
  "script",
  "style",
  "textarea",
  "input",
]);

type HastNode = {
  type: string;
  value?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
};

function rehypeBundledEmoji() {
  return (tree: HastNode) => {
    replaceEmojiNodes(tree);
  };
}

function replaceEmojiNodes(node: HastNode, shouldSkip = false): void {
  if (!node.children) {
    return;
  }

  const nextChildren: HastNode[] = [];

  for (const child of node.children) {
    if (
      child.type === "text" &&
      typeof child.value === "string" &&
      !shouldSkip
    ) {
      const segments = splitEmojiText(child.value);
      if (segments.length === 1 && segments[0]?.kind === "text") {
        nextChildren.push(child);
        continue;
      }

      for (const segment of segments) {
        if (segment.kind === "text") {
          nextChildren.push({ type: "text", value: segment.value });
          continue;
        }

        nextChildren.push({
          type: "element",
          tagName: "img",
          properties: {
            alt: segment.value,
            className: ["emoji-inline"],
            decoding: "async",
            draggable: false,
            src: segment.src,
          },
          children: [],
        });
      }

      continue;
    }

    replaceEmojiNodes(child, shouldSkip || shouldSkipEmojiReplacement(child));
    nextChildren.push(child);
  }

  node.children = nextChildren;
}

function shouldSkipEmojiReplacement(node: HastNode): boolean {
  if (node.type !== "element") {
    return false;
  }

  if (node.tagName && EMOJI_SKIP_TAGS.has(node.tagName)) {
    return true;
  }

  const classNames = getClassNames(node.properties?.className);
  return classNames.includes("katex") || classNames.includes("emoji-inline");
}

function getClassNames(value: unknown): string[] {
  if (typeof value === "string") {
    return value.split(/\s+/).filter(Boolean);
  }

  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string");
  }

  return [];
}

export function MarkdownContent({ content }: { content: string }) {
  const remarkPlugins = useMemo(() => [remarkGfm, remarkMath], []);
  const rehypePluginsAsync = useMemo((): PluggableList => {
    return [
      [rehypePrettyCode, PRETTY_CODE_OPTIONS],
      [rehypeKatex, KATEX_OPTIONS],
      rehypeBundledEmoji,
    ];
  }, []);
  /** Sync `Markdown` cannot run `rehype-pretty-code` (Shiki is async). */
  const rehypePluginsFallback = useMemo((): PluggableList => {
    return [[rehypeKatex, KATEX_OPTIONS], rehypeBundledEmoji];
  }, []);

  const components = useMemo<Components>(
    () => ({
        a: (props) => (
        <a {...props} target="_blank" rel="noreferrer noopener" />
      ),
      pre: MarkdownPre,
    }),
    [],
  );

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
