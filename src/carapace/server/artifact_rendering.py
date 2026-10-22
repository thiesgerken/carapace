from __future__ import annotations

ARTIFACT_SANDBOX = "allow-scripts"


def artifact_headers() -> dict[str, str]:
    return {
        "Content-Security-Policy": (
            f"sandbox {ARTIFACT_SANDBOX}; default-src 'none'; "
            "script-src 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net/npm/; "
            "style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
            "img-src data: blob:; connect-src 'none'; form-action 'none'; frame-ancestors 'self'"
        ),
        "X-Content-Type-Options": "nosniff",
    }
