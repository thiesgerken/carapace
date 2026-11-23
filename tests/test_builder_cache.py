"""The builder's binary cache listener: own store first, then upstreams, reads of cache paths only."""

from __future__ import annotations

import httpx
import pytest
from compression import zstd
from fastapi.testclient import TestClient

from carapace.builder.cache import create_cache_app
from carapace.builder.models import UpstreamCache

HASH = "0z5c0imb0fnaf9a3ab2s1a39xh1g8gqi"
UPSTREAMS = [
    UpstreamCache(url="https://first.example", public_key="first-1:AAAA"),
    UpstreamCache(url="https://second.example", public_key="second-1:BBBB"),
]
NARINFO = f"StorePath: /nix/store/{HASH}-hello\nURL: nar/1abc.nar.xz\nCompression: xz\nSig: second-1:sig\n"


# NAR responses use `stream=`: httpx reads `content=` up front, and the cache relays raw, unread streams.
def cache(routes: dict[str, httpx.Response]) -> tuple[TestClient, list[str]]:
    """A cache app whose network answers *routes* (absolute URLs), 404 otherwise; returns the requests."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        return routes.get(url, httpx.Response(404))

    return TestClient(create_cache_app(UPSTREAMS, httpx.MockTransport(handler))), seen


def test_the_builders_own_path_comes_from_harmonia() -> None:
    client, seen = cache({f"http://127.0.0.1:5000/{HASH}.narinfo": httpx.Response(200, text="own")})

    assert client.get(f"/{HASH}.narinfo").text == "own"
    assert seen == [f"http://127.0.0.1:5000/{HASH}.narinfo"]


def test_an_upstream_narinfo_keeps_its_signature_and_points_its_nar_through_here() -> None:
    client, _ = cache({f"https://second.example/{HASH}.narinfo": httpx.Response(200, text=NARINFO)})

    body = client.get(f"/{HASH}.narinfo").text

    assert "URL: upstream/1/nar/1abc.nar.xz\n" in body
    assert "Sig: second-1:sig\n" in body


def test_an_upstream_redirect_is_followed_here_and_never_reaches_the_sandbox() -> None:
    client, seen = cache(
        {
            f"https://first.example/{HASH}.narinfo": httpx.Response(
                302, headers={"Location": f"https://mirror.example/{HASH}.narinfo"}
            ),
            f"https://mirror.example/{HASH}.narinfo": httpx.Response(200, text=NARINFO),
            "https://first.example/nar/1abc.nar.xz": httpx.Response(
                307, headers={"Location": "https://cdn.example/nar/1abc.nar.xz"}
            ),
            "https://cdn.example/nar/1abc.nar.xz": httpx.Response(200, stream=httpx.ByteStream(b"nar bytes")),
        }
    )

    narinfo = client.get(f"/{HASH}.narinfo", follow_redirects=False)
    nar = client.get("/upstream/0/nar/1abc.nar.xz", follow_redirects=False)

    assert (narinfo.status_code, "location" in narinfo.headers) == (200, False)
    assert "URL: upstream/0/nar/1abc.nar.xz" in narinfo.text
    assert (nar.status_code, nar.content, "location" in nar.headers) == (200, b"nar bytes", False)
    assert "https://cdn.example/nar/1abc.nar.xz" in seen


def test_an_upstream_error_is_a_502_not_a_404() -> None:
    client, _ = cache({f"https://first.example/{HASH}.narinfo": httpx.Response(500)})
    assert client.get(f"/{HASH}.narinfo").status_code == 502


def test_a_path_nobody_has_is_a_404() -> None:
    client, _ = cache({})
    assert client.get(f"/{HASH}.narinfo").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/builds/abc",
        "/info",
        "/upstream/0/builds",
        "/upstream/2/nar/1abc.nar.xz",
        "/nar/../builds",
        "/serve/abc/index.html",
        f"/{HASH}.ls",
        f"/log/{HASH}-hello.drv",
    ],
)
def test_anything_but_cache_reads_is_refused_without_asking_anyone(path: str) -> None:
    client, seen = cache({})
    assert client.get(path).status_code == 404
    assert seen == []


def test_writes_are_refused() -> None:
    client, seen = cache({})
    assert client.put(f"/{HASH}.narinfo", content=b"x").status_code == 405
    assert seen == []


def test_own_nars_keep_harmonias_query_and_encoding() -> None:
    client, seen = cache(
        {
            "http://127.0.0.1:5000/nar/04zw.nar?hash=abc": httpx.Response(
                200, stream=httpx.ByteStream(zstd.compress(b"nar bytes")), headers={"Content-Encoding": "zstd"}
            )
        }
    )

    response = client.get("/nar/04zw.nar?hash=abc", headers={"Accept-Encoding": "zstd"})

    # Relayed still encoded: the client decodes it once, as its header says.
    assert (response.headers["content-encoding"], response.content) == ("zstd", b"nar bytes")
    assert seen == ["http://127.0.0.1:5000/nar/04zw.nar?hash=abc"]
