from __future__ import annotations

import argparse
import json
import sys

from web_skill.backends import get_backend, result_to_dict


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search the web using a configurable backend (default: Brave).",
    )
    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=5,
        help="Number of results (default: 5)",
    )
    parser.add_argument(
        "-b",
        "--backend",
        default="brave",
        help="Search backend (default: brave)",
    )
    parser.add_argument("--country", help="2-letter ISO country code (e.g. US, DE)")
    parser.add_argument("--language", help="ISO 639-1 language code (e.g. en, de)")
    parser.add_argument(
        "--freshness",
        choices=["day", "week", "month", "year"],
        help="Time filter for results",
    )
    args = parser.parse_args()

    backend = get_backend(args.backend)
    results = backend.search(
        args.query,
        count=args.count,
        country=args.country,
        language=args.language,
        freshness=args.freshness,
    )

    output = {
        "query": args.query,
        "backend": backend.name,
        "resultCount": len(results),
        "results": [result_to_dict(r) for r in results],
    }
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
