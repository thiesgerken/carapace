export function artifactSlugFromPath(path: string): string | null {
  const slug = /^artifacts\/([^/\\]+)\/index\.html$/.exec(path)?.[1];
  return slug && slug !== "." && slug !== ".." ? slug : null;
}

export function sentArtifactSlug(path: unknown): string | null {
  return typeof path === "string" && path.startsWith("/workspace/")
    ? artifactSlugFromPath(path.slice("/workspace/".length))
    : null;
}

export function artifactSnapshotTitle(source: string, slug: string): string {
  return new window.DOMParser().parseFromString(source, "text/html").title.trim() || slug;
}

export function artifactViewerHref(slug: string): string {
  return `/artifacts?slug=${encodeURIComponent(slug)}`;
}
