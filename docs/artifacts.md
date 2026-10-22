# Artifacts

Artifacts are HTML pages stored in the user's knowledge repository at
`artifacts/<slug>/index.html`. The slug is the directory name; a directory without
`index.html` is not an artifact. Each page must be self-contained: everything is
inline (data: URIs, inline SVG/CSS/JS, or the allowed CDNs).
Changes use the normal sentinel-reviewed Git push workflow.

## Agent workflow

The agent writes `/workspace/artifacts/<slug>/index.html`, commits and pushes it,
then uses `send_file` to show a snapshot in chat. Every push updates the live
knowledge view and any existing shared link; old chat snapshots stay unchanged.
See the bundled [artifacts skill](../src/carapace/assets/skills/artifacts/SKILL.md)
for the authoring contract and checks. The sandbox ships no browser, so inspect
the rendered page's narrow layout, light/dark appearance, and keyboard controls
yourself.

## Browsing and chat snapshots

The knowledge browser marks artifact directories with an artifact icon and uses
`index.html`'s `<title>` as their label beside the slug. Only the artifact's
`index.html` renders in a sandboxed iframe, with controls to inspect its source or
open it in a new tab. Other HTML files browse normally. The normal knowledge
download remains available.

The agent uses the existing `send_file` tool to show an HTML page in chat. Its
preview renders the persisted sent-file copy, so history keeps that snapshot even
when the repository changes. The knowledge browser renders the current working
tree. Both views require self-contained HTML; adjacent files are not served by the
artifact renderer. Opaque-origin subresource requests do not carry the app's
`SameSite=Lax` session cookie.

## Rendering policy

`GET /api/artifacts/<slug>` serves only `artifacts/<slug>/index.html`.
Authentication and knowledge read access are required. Invalid slug segments,
escaping symlinks, and `.git` paths return 404. Sent HTML uses
`GET /api/sessions/<session_id>/files/<file_id>?artifact=1`, with the normal session
ownership check.

Both rendering paths set the real MIME type, `X-Content-Type-Options: nosniff`, and
the same `Content-Security-Policy`:

```text
sandbox allow-scripts; default-src 'none';
script-src 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net/npm/;
style-src 'unsafe-inline' https://fonts.googleapis.com;
font-src https://fonts.gstatic.com; img-src data: blob:;
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

## Sharing

The knowledge artifact view has a **Share publicly** switch. Enabling it asks for
confirmation that anyone with the link can see the page, including future agent
changes. While sharing is on, the view shows the public link and a copy action.
Sharing is controlled by the authenticated user, not by files in the knowledge
repository.

Sharing state lives in the database, keyed by owner and slug. A row is created on
the first enable action. Enabling an already-shared artifact preserves its token
and sharing timestamp. Disabling clears the token immediately; enabling after
that issues a new token, and old links stay invalid. Share tokens are never stored
in the repo or provided to the agent.

Management endpoints require a browser cookie session. API keys are rejected,
even with `knowledge:write`, because the agent can hold a scoped API key and must
not be able to publish artifacts or read share tokens.

- `GET /api/artifacts/<slug>/share` returns the current URL and sharing timestamp,
  or null values while sharing is off.
- `PUT /api/artifacts/<slug>/share` enables sharing and returns its URL.
- `DELETE /api/artifacts/<slug>/share` disables sharing, even if the artifact was
  deleted or renamed.

The API returns the public path relative to the backend origin. The UI resolves
it against that origin to display and copy an absolute URL.

`GET /api/public/a/<token>` requires no login and serves only the resolved owner's
`artifacts/<slug>/index.html`. It reuses the authenticated renderer's confinement
checks and unchanged CSP headers, with `Referrer-Policy: no-referrer` and
`Cache-Control: no-store`. Unknown or revoked tokens, missing artifacts, and
escaping paths all return the same 404 response. There are no asset paths.

The route is under `/api` so existing production routing sends it to the backend.
The Helm HTTPRoute sends `/api` to the server and other paths to static frontend
nginx; a top-level `/a/...` URL would reach the static server instead.

Shared links serve the current knowledge working tree, not a chat snapshot.
Renaming or deleting the directory makes its link return 404; the link does not
follow renames. A push touching a currently shared artifact adds a notice to the
sentinel context that the artifact is publicly reachable without authentication
and the change is a publication. Only the shared artifacts actually touched are
named, including deletions and renames. The sentinel receives slugs, not tokens.
YOLO mode bypasses this review like other push evaluation.

## Size limit

The Git pre-receive hook totals the uncompressed blob sizes under each
`artifacts/<slug>/` directory in the incoming tree, including nested assets. Each
directory may contain at most **10 MiB (10,485,760 bytes)**. Larger directories are
rejected before their push is sent to the sentinel, with an error naming the
artifact. Different artifact directories have separate limits.
