from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urlparse

import httpx
import trafilatura

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        print(
            f"Error: Invalid URL scheme '{parsed.scheme}'. Only http and https are supported.",
            file=sys.stderr,
        )
        sys.exit(1)
    return url


def _extract_html(
    html: str,
    url: str,
    mode: str,
) -> tuple[str | None, str | None]:
    """Extract main content and title from HTML using trafilatura.

    Returns (content, title).
    """
    output_format = "txt" if mode == "text" else "markdown"

    # Get title via bare_extraction (available even when text extraction is sparse)
    bare = trafilatura.bare_extraction(
        html,
        url=url,
        output_format=output_format,
        include_links=True,
        include_tables=True,
        include_formatting=True,
        with_metadata=True,
    )
    title = bare.title if bare and hasattr(bare, "title") else None

    # Get formatted content via extract() which handles the full pipeline
    content = trafilatura.extract(
        html,
        url=url,
        output_format=output_format,
        include_links=True,
        include_tables=True,
        include_formatting=True,
        with_metadata=False,
    )

    return content, title


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch a URL and extract readable content (HTML → markdown/text).",
    )
    parser.add_argument("url", help="URL to fetch (http or https)")
    parser.add_argument(
        "-m",
        "--mode",
        choices=["markdown", "text"],
        default="markdown",
        help="Extraction mode (default: markdown)",
    )
    parser.add_argument(
        "-c",
        "--max-chars",
        type=int,
        default=None,
        help="Truncate output to this many characters",
    )
    parser.add_argument(
        "--user-agent",
        default=_DEFAULT_USER_AGENT,
        help="Override User-Agent header",
    )
    args = parser.parse_args()

    url = _validate_url(args.url)

    try:
        with httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            resp = client.get(
                url,
                headers={
                    "User-Agent": args.user_agent,
                    "Accept": "text/markdown, text/html;q=0.9, */*;q=0.1",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
    except httpx.HTTPError as exc:
        output = {"url": url, "error": str(exc)}
        json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
        print()
        sys.exit(1)

    final_url = str(resp.url)
    content_type_raw = resp.headers.get("content-type", "application/octet-stream")
    content_type = content_type_raw.split(";")[0].strip().lower()
    body = resp.text

    title: str | None = None
    truncated = False

    if resp.status_code >= 400:
        content = body[:2000] if body else resp.reason_phrase
        output = {
            "url": url,
            "finalUrl": final_url,
            "status": resp.status_code,
            "contentType": content_type,
            "error": f"HTTP {resp.status_code}: {resp.reason_phrase}",
            "detail": content,
        }
        json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
        print()
        sys.exit(1)

    if "text/html" in content_type:
        content, title = _extract_html(body, final_url, args.mode)
        if content is None:
            content = body
            title = None
    elif "application/json" in content_type:
        try:
            content = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            content = body
    elif "text/markdown" in content_type:
        content = body
    else:
        content = body

    if args.max_chars is not None and content:
        content, truncated = _truncate(content, args.max_chars)

    output = {
        "url": url,
        "finalUrl": final_url,
        "status": resp.status_code,
        "contentType": content_type,
        "extractMode": args.mode,
        "content": content or "",
        "contentLength": len(content) if content else 0,
        "truncated": truncated,
    }
    if title:
        output["title"] = title

    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
