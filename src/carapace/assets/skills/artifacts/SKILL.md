---
name: artifacts
description: >-
  Build self-contained HTML artifacts: reports, dashboards, calculators, and
  interactive explainers that render in carapace chat and the knowledge browser.
  Use when the user needs a reusable page or local interaction rather than a
  short answer, a Mermaid diagram, or a downloadable file.
---

# Artifacts

Build one self-contained page at `/workspace/artifacts/<slug>/index.html`.
The knowledge browser shows the current pushed version; `send_file` shows a
snapshot in chat. The user can share the live page from the knowledge browser.

## Choose the smallest useful format

| Need | Format |
| --- | --- |
| A direct answer, a short explanation, or a few comparable values | Chat prose or a table |
| Relationships, a sequence, a state machine, or a system diagram | Mermaid in the chat reply |
| An existing document, dataset, export, or image to download | Plain `send_file` |
| A reusable report, a dashboard with several views, or a local calculator/explainer | Artifact |

Do not turn a simple answer into a page just because HTML is available.

## Safety and rendering contract

- Use a stable, descriptive slug such as `release-readiness`; the entry point is
  always `index.html`, with a meaningful `<title>` and a viewport meta tag.
- Keep the page self-contained: inline SVG, CSS, JavaScript, and data; use data
  URIs for raster images. Adjacent files and relative asset URLs are not served.
- Treat every artifact as possibly public. Include no secrets, credentials,
  tokens, or private data beyond what the user asked to include. Do not inspect
  sharing state, request share tokens, or try to enable sharing. Sharing is a
  browser-only user action, and you are not told which artifacts are shared.
- Keep the entire `artifacts/<slug>/` directory at or below **10 MiB
  (10,485,760 bytes)**, including any other files left in it. Oversized pushes are
  rejected before sentinel review.
- Make no runtime data or network calls. `connect-src 'none'` blocks `fetch`, XHR,
  WebSocket, EventSource, and `sendBeacon`. Embed the data the page needs; no API
  access, telemetry, remote images, or server-backed forms.
- The only external resource exceptions are JavaScript from
  `https://cdnjs.cloudflare.com/` or `https://cdn.jsdelivr.net/npm/`, with an
  **exact pinned version in every library URL**, plus Google Fonts styles from
  `https://fonts.googleapis.com/` and font files from `https://fonts.gstatic.com/`.
  Prefer inline code and system fonts when a dependency adds little. No `latest`,
  version ranges, unversioned URLs, CDN stylesheets, or extra origins.
- The iframe has no popups or top navigation: links that open a new tab or target
  the parent page do not work. Put all external links in the **chat reply**, not
  inside the artifact.
  Never write navigation code (`location`, `window.open`, meta refresh, or
  programmatically followed links). The sentinel treats navigation with embedded
  data as exfiltration and will deny such a push; do not try to bypass that check.
- Do not access cookies, the parent page, local/session storage, or service
  workers. The CSP sandbox gives the page an opaque origin, including when opened
  directly. Keep interactive state in the current page's memory only.
- Use `prefers-color-scheme` for light/dark styling. The app does not pass its
  selected theme into the iframe.

The sandbox is not a navigation firewall: a page can still navigate itself.
The prohibition on navigation is a safety requirement, not a browser guarantee.
Sentinel review is best effort, including for obfuscated code.

## Build and deliver

1. Pick the format above. For an artifact, read
   [design.md](references/design.md), then choose a complete starting page from
   [patterns.md](references/patterns.md). Read
   [charts.md](references/charts.md) if a chart helps explain the data.
2. Write `/workspace/artifacts/<slug>/index.html`. Replace the sample content and
   title with the user's subject. Keep all data and behavior inside that page.
3. Check the page at 375px and a desktop width, in light and dark mode. Exercise
   every control with the keyboard. Verify the calculations and any chart labels,
   units, and baselines; label example or estimated data honestly.
4. Inspect the directory size and your Git diff. Stage only the artifact paths,
   then commit and push from the knowledge checkout, for example:

   ```sh
   git -C /workspace add artifacts/release-readiness/index.html
   git -C /workspace commit -m "Add release readiness report"
   git -C /workspace push
   ```

   A push updates the knowledge browser **and any existing shared link**. Even
   though you do not know the sharing state, treat a revision as potentially
   public. If the sentinel denies the push, address the reason; do not bypass it.
5. After the push succeeds, call `send_file` with
   `path="/workspace/artifacts/release-readiness/index.html"` (using your slug).
   This displays the HTML snapshot in chat. Put source links and any necessary
   caveats in the surrounding chat reply, not inside navigable artifact links.
6. To update the same artifact, edit the **same path**, commit, push, and
   `send_file` the entry point again. Old chat cards keep their snapshots; the
   knowledge browser and shared link show the latest pushed content. Renaming the
   slug creates a different identity and breaks the old shared URL.

No new tool, provider, credential, or setup step is needed for this skill.
