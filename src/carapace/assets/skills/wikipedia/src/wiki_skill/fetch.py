"""Wikipedia fetch — retrieve article content via the Wikipedia API."""

import argparse
import json
import sys
import urllib.parse

import httpx


def fetch_article(page_title: str, lang: str = "de") -> dict:
    """Fetch a Wikipedia article's plaintext extract via the TextExtracts API."""
    base_url = f"https://{lang}.wikipedia.org/w/api.php"

    # Use TextExtracts API for clean plaintext (no HTML parsing needed)
    params = {
        "action": "query",
        "titles": page_title.replace("_", " "),
        "prop": "extracts|info",
        "explaintext": "1",
        "exsectionformat": "wiki",
        "inprop": "url|displaytitle",
        "format": "json",
        "origin": "*",
    }

    with httpx.Client(timeout=15.0) as client:
        resp = client.get(base_url, params=params)

    if resp.status_code != 200:
        print(
            f"Fehler: Wikipedia API returned {resp.status_code}: {resp.text}",
            file=sys.stderr,
        )
        sys.exit(1)

    data = resp.json()
    pages = data.get("query", {}).get("pages", {})

    if not pages:
        print(f"Fehler: Keine Seite gefunden für '{page_title}'", file=sys.stderr)
        sys.exit(1)

    # pages is keyed by page ID; -1 means not found
    page_id, page_data = next(iter(pages.items()))

    if page_id == "-1" or "missing" in page_data:
        # Try a search fallback to suggest alternatives
        suggestions = _search_suggestions(base_url, page_title)
        msg = f"Fehler: Seite '{page_title}' nicht gefunden."
        if suggestions:
            msg += f" Meintest du: {', '.join(suggestions)}?"
        print(msg, file=sys.stderr)
        sys.exit(1)

    title = page_data.get("title", page_title)
    extract = page_data.get("extract", "")

    return {
        "pageid": int(page_id),
        "title": title,
        "url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title)}",
        "lang": lang,
        "content": extract,
        "contentLength": len(extract),
    }


def _search_suggestions(base_url: str, query: str) -> list[str]:
    """Return up to 3 search suggestions for a missing page."""
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query.replace("_", " "),
        "srlimit": 3,
        "format": "json",
        "origin": "*",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(base_url, params=params)
        if resp.status_code == 200:
            results = resp.json().get("query", {}).get("search", [])
            return [r["title"] for r in results]
    except httpx.HTTPError:
        pass
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Lade den Inhalt eines Wikipedia-Artikels")
    parser.add_argument("page", help="Seitenname (Leerzeichen oder Unterstriche)")
    parser.add_argument("--lang", choices=["de", "en"], default="de", help="Sprachcode (default: de)")
    parser.add_argument(
        "-c",
        "--max-chars",
        type=int,
        default=None,
        help="Inhalt auf diese Zeichenzahl kürzen",
    )
    args = parser.parse_args()

    article = fetch_article(args.page, lang=args.lang)

    if args.max_chars is not None and len(article["content"]) > args.max_chars:
        article["content"] = article["content"][: args.max_chars]
        article["contentLength"] = args.max_chars
        article["truncated"] = True
    else:
        article["truncated"] = False

    json.dump(article, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
