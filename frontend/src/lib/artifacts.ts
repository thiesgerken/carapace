export function artifactSlugFromPath(path: string): string | null {
  const slug = /^artifacts\/([^/\\]+)\/index\.html$/.exec(path)?.[1];
  return slug && slug !== "." && slug !== ".." ? slug : null;
}

export function artifactViewerHref(slug: string): string {
  return `/artifacts?slug=${encodeURIComponent(slug)}`;
}
