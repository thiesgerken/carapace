import type { ChatMessage } from "@/lib/types";

export function artifactSlugFromPath(path: string): string | null {
  const slug = /^artifacts\/([^/\\]+)\/index\.html$/.exec(path)?.[1];
  return slug && slug !== "." && slug !== ".." ? slug : null;
}

export function artifactViewerHref(slug: string): string {
  return `/artifacts?slug=${encodeURIComponent(slug)}`;
}

export interface ArtifactReference {
  slug: string;
  /** A later reference to a slug this session already showed. */
  update: boolean;
  /** How many references the session holds to this slug; a new one makes every preview of it reload. */
  revision: number;
}

/** The artifact reference behind each successful `show_artifact` call, keyed by message index. */
export function artifactReferences(messages: ChatMessage[]): Map<number, ArtifactReference> {
  const shown: Array<[number, string]> = [];
  messages.forEach((message, index) => {
    if (message.kind === "tool_call" && message.tool === "show_artifact" && message.exitCode === 0 && typeof message.args.slug === "string") {
      shown.push([index, message.args.slug]);
    }
  });
  const counts = new Map<string, number>();
  for (const [, slug] of shown) counts.set(slug, (counts.get(slug) ?? 0) + 1);
  const seen = new Set<string>();
  return new Map(shown.map(([index, slug]) => {
    const update = seen.has(slug);
    seen.add(slug);
    return [index, { slug, update, revision: counts.get(slug)! }];
  }));
}
