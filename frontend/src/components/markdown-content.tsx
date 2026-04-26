"use client";

import { useEffect, useMemo, useRef } from "react";
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
const EMOJI_SKIP_SELECTOR = "code, pre, script, style, textarea, input, .katex, .emoji-inline";

function replaceEmojiTextNodes(root: HTMLElement): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];

  let current = walker.nextNode();
  while (current) {
    const textNode = current as Text;
    if (shouldReplaceTextNode(textNode)) {
      nodes.push(textNode);
    }
    current = walker.nextNode();
  }

  for (const textNode of nodes) {
    const segments = splitEmojiText(textNode.data);
    if (segments.length === 1 && segments[0]?.kind === "text") {
      continue;
    }

    const fragment = document.createDocumentFragment();
    for (const segment of segments) {
      if (segment.kind === "text") {
        fragment.append(document.createTextNode(segment.value));
        continue;
      }

      const image = document.createElement("img");
      image.className = "emoji-inline";
      image.src = segment.src;
      image.alt = segment.value;
      image.decoding = "async";
      image.draggable = false;
      image.addEventListener(
        "error",
        () => {
          image.replaceWith(document.createTextNode(segment.value));
        },
        { once: true },
      );
      fragment.append(image);
    }

    textNode.replaceWith(fragment);
  }
}

function shouldReplaceTextNode(textNode: Text): boolean {
  if (!textNode.data) {
    return false;
  }

  const parent = textNode.parentElement;
  if (!parent) {
    return false;
  }

  if (parent.closest(EMOJI_SKIP_SELECTOR)) {
    return false;
  }

  const segments = splitEmojiText(textNode.data);
  return !(segments.length === 1 && segments[0]?.kind === "text");
}

export function MarkdownContent({ content }: { content: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
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

  const components = useMemo<Components>(
    () => ({
      a: (props) => (
        <a {...props} target="_blank" rel="noreferrer noopener" />
      ),
      pre: MarkdownPre,
    }),
    [],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    let rafId = 0;

    const applyEmojiReplacement = () => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        replaceEmojiTextNodes(container);
      });
    };

    applyEmojiReplacement();

    const observer = new MutationObserver(() => {
      applyEmojiReplacement();
    });

    observer.observe(container, {
      characterData: true,
      childList: true,
      subtree: true,
    });

    return () => {
      cancelAnimationFrame(rafId);
      observer.disconnect();
    };
  }, [content]);

  return (
    <div className="prose" ref={containerRef}>
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
