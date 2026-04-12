"""Wikipedia search — query the Wikipedia API for articles."""

import argparse
import json
import sys
import urllib.parse

import httpx


def search_wikipedia(
    query: str,
    lang: str = "de",
    limit: int = 10,
) -> list[dict]:
    base_url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": limit,
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
    raw_results = data.get("query", {}).get("search", [])

    results: list[dict] = []
    for item in raw_results:
        title = item.get("title", "")
        results.append(
            {
                "title": title,
                "snippet": item.get("snippet", ""),
                "pageid": item.get("pageid"),
                "url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title)}",
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Suche nach Wikipedia-Artikeln")
    parser.add_argument("query", help="Suchbegriff")
    parser.add_argument("--lang", choices=["de", "en"], default="de", help="Sprachcode (default: de)")
    parser.add_argument("-n", "--limit", type=int, default=10, help="Max. Trefferzahl (default: 10)")
    args = parser.parse_args()

    results = search_wikipedia(args.query, lang=args.lang, limit=args.limit)

    output = {
        "query": args.query,
        "lang": args.lang,
        "resultCount": len(results),
        "results": results,
    }
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
