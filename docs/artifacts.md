# Artifacts

Artifacts are HTML pages stored in the user's knowledge repository at
`artifacts/<slug>/index.html`. Optional assets live in the same directory. The slug
is the directory name; a directory without `index.html` is not an artifact.
Changes use the normal sentinel-reviewed Git push workflow.

## Browsing and chat snapshots

The knowledge browser marks artifact directories with an artifact icon and uses
`index.html`'s `<title>` as their label. HTML files inside an artifact render in a
sandboxed iframe, with controls to inspect their source or open them in a new tab.
The normal knowledge download remains available.

The agent uses the existing `send_file` tool to show an HTML page in chat. Its
preview renders the persisted sent-file copy, so history keeps that snapshot even
when the repository changes. The knowledge browser renders the current working
tree. Inline assets when a chat snapshot must be self-contained; adjacent assets
are available through the knowledge artifact route.

## Rendering policy

`GET /api/artifacts/<slug>/` serves `index.html`; paths below that URL serve files
from the same artifact directory. Authentication and knowledge read access are
required. Traversal, escaping symlinks, and `.git` paths return 404. Sent HTML uses
`GET /api/sessions/<session_id>/files/<file_id>?artifact=1`, with the normal session
ownership check.

Both rendering paths set the real MIME type, `X-Content-Type-Options: nosniff`, and
the same `Content-Security-Policy`:

```text
sandbox allow-scripts; default-src 'none';
script-src 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net/npm/;
style-src 'unsafe-inline' https://fonts.googleapis.com;
font-src https://fonts.gstatic.com; img-src data: blob: 'self';
connect-src 'none'; form-action 'none'; frame-ancestors 'self'
```

The iframe also has `sandbox="allow-scripts"`. The response header applies the
sandbox even when the page is opened directly. Without `allow-same-origin`, scripts
cannot read application cookies or the parent document. Fetch/XHR/WebSocket,
external images, and form submissions are blocked. Theme selection uses the artifact's own
`prefers-color-scheme` rules; the app does not pass its theme into the frame.

An artifact script can still navigate its own frame or tab to an external URL,
including automatically when the page is viewed. Sandboxed documents may navigate
themselves, and CSP does not govern document navigation. A URL carrying private
data embedded in the artifact can therefore leak that data without a click,
outside the sandbox egress proxy.

When a push touches `artifacts/`, the sentinel's push evaluation includes a notice
to treat external navigation carrying embedded private data as exfiltration.
Deletions count as touched paths too. This review is best effort against
obfuscated code; it does not prevent document navigation.

## Size limit

The Git pre-receive hook totals the uncompressed blob sizes under each
`artifacts/<slug>/` directory in the incoming tree, including nested assets. Each
directory may contain at most **10 MiB (10,485,760 bytes)**. Larger directories are
rejected before their push is sent to the sentinel, with an error naming the
artifact. Different artifact directories have separate limits.
