from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    age: str | None = None


class SearchBackend(Protocol):
    """Protocol for pluggable web search backends."""

    name: str

    def search(
        self,
        query: str,
        *,
        count: int = 5,
        country: str | None = None,
        language: str | None = None,
        freshness: str | None = None,
    ) -> list[SearchResult]: ...


class BraveBackend:
    """Brave Search API backend."""

    name = "brave"

    _BASE_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self) -> None:
        self._api_key = os.environ.get("BRAVE_API_KEY", "")
        if not self._api_key:
            print(
                "Error: BRAVE_API_KEY is not set.\n"
                "Get a key at https://brave.com/search/api/ and declare it in carapace.yaml "
                "or export BRAVE_API_KEY in your environment.",
                file=sys.stderr,
            )
            sys.exit(1)

    def search(
        self,
        query: str,
        *,
        count: int = 5,
        country: str | None = None,
        language: str | None = None,
        freshness: str | None = None,
    ) -> list[SearchResult]:
        params: dict[str, str | int] = {"q": query, "count": count}
        if country:
            params["country"] = country
        if language:
            params["search_lang"] = language
        if freshness:
            params["freshness"] = freshness

        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                self._BASE_URL,
                params=params,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self._api_key,
                },
            )

        if resp.status_code != 200:
            print(
                f"Error: Brave API returned {resp.status_code}: {resp.text}",
                file=sys.stderr,
            )
            sys.exit(1)

        data = resp.json()
        web_results = data.get("web", {}).get("results", [])

        results: list[SearchResult] = []
        for item in web_results:
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", ""),
                    age=item.get("age"),
                )
            )
        return results


_BACKENDS: dict[str, type[SearchBackend]] = {
    "brave": BraveBackend,  # type: ignore[dict-item]
}


def get_backend(name: str = "brave") -> SearchBackend:
    """Return an instantiated search backend by name."""
    cls = _BACKENDS.get(name)
    if cls is None:
        available = ", ".join(sorted(_BACKENDS))
        print(
            f"Error: Unknown search backend '{name}'. Available: {available}",
            file=sys.stderr,
        )
        sys.exit(1)
    return cls()


def result_to_dict(result: SearchResult) -> dict:
    d = asdict(result)
    if d["age"] is None:
        del d["age"]
    return d
