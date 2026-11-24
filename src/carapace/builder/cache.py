"""The builder's binary cache: its own store through harmonia, then the upstream caches.

Sandboxes substitute only from here, through their session proxy. harmonia serves and signs the
builder's store on loopback; this listener adds the upstreams behind one URL. An upstream narinfo
keeps its signature (which does not cover `URL:`), only its NAR URL is rewritten to
`upstream/<i>/…` so that the NAR comes through here too. Redirects are followed here, to public
https hosts only, never handed to a sandbox, and an upstream failure stays a 502: a 404 would
make Nix cache the path as missing.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from loguru import logger
from starlette.background import BackgroundTask

from ..sandbox.destinations import DestinationPolicy, DestinationRefusedError
from .models import UpstreamCache, cache_path_allowed

HARMONIA_URL = "http://127.0.0.1:5000"
CACHE_INFO = "StoreDir: /nix/store\nWantMassQuery: 1\nPriority: 30\n"
_PASSED_HEADERS = ("content-type", "content-length", "content-encoding")


class _UpstreamError(Exception):
    pass


async def _refuse_internal_redirect(response: httpx.Response) -> None:
    """Follow an upstream's redirect only to a public https host.

    The builder has unrestricted egress, so a redirect to an internal address would stream that
    response into a sandbox. The target is resolved here and again when httpx connects, so a DNS
    answer that changes in between still gets through; this needs a malicious upstream to begin with.
    """
    if not response.has_redirect_location:
        return
    target = response.url.join(response.headers["location"])
    try:
        if target.scheme != "https":
            raise DestinationRefusedError(f"{target.scheme} is not https")
        await DestinationPolicy().resolve(target.host, target.port or 443)
    except (DestinationRefusedError, OSError) as exc:
        # An httpx error, so callers answer it like any other upstream failure: a 502.
        raise httpx.RequestError(f"Refused redirect to {target}: {exc}", request=response.request) from exc


def _rewrite_nar_url(narinfo: str, index: int) -> str:
    lines = []
    for line in narinfo.splitlines():
        if line.startswith("URL: "):
            url = line.removeprefix("URL: ")
            if not cache_path_allowed(f"/{url.split('?', 1)[0]}"):
                raise _UpstreamError(f"upstream {index} names an unsupported NAR URL: {url}")
            line = f"URL: upstream/{index}/{url}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def create_cache_app(upstreams: Sequence[UpstreamCache], transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """*transport* replaces the network for both harmonia and the upstreams (tests)."""
    harmonia = httpx.AsyncClient(base_url=HARMONIA_URL, timeout=60, transport=transport)
    upstream_client = httpx.AsyncClient(
        follow_redirects=True,
        timeout=60,
        transport=transport,
        event_hooks={"response": [_refuse_internal_redirect]},
    )
    app = FastAPI(title="Carapace builder cache")
    app.router.on_shutdown.extend([harmonia.aclose, upstream_client.aclose])

    async def stream(client: httpx.AsyncClient, url: str, request: Request) -> Response:
        upstream_request = client.build_request(
            request.method, url, headers={"Accept-Encoding": request.headers.get("accept-encoding", "identity")}
        )
        try:
            response = await client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            logger.warning(f"Cache: {url} failed: {exc}")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Cache source unavailable") from exc
        if response.status_code != httpx.codes.OK:
            await response.aclose()
            if response.status_code == httpx.codes.NOT_FOUND:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Cache source answered {response.status_code}")
        headers = {name: response.headers[name] for name in _PASSED_HEADERS if name in response.headers}
        # Raw bytes: a zstd-encoded NAR from harmonia stays encoded, as its header says.
        return StreamingResponse(response.aiter_raw(), headers=headers, background=BackgroundTask(response.aclose))

    async def upstream_narinfo(name: str) -> str | None:
        failed = False
        for index, upstream in enumerate(upstreams):
            try:
                response = await upstream_client.get(f"{upstream.url}/{name}")
            except httpx.HTTPError as exc:
                logger.warning(f"Cache: upstream {upstream.url} failed for {name}: {exc}")
                failed = True
                continue
            if response.status_code == httpx.codes.OK:
                return _rewrite_nar_url(response.text, index)
            if response.status_code != httpx.codes.NOT_FOUND:
                logger.warning(f"Cache: upstream {upstream.url} answered {response.status_code} for {name}")
                failed = True
        if failed:
            raise _UpstreamError("an upstream cache failed")
        return None

    @app.api_route("/nix-cache-info", methods=["GET", "HEAD"])
    async def cache_info() -> Response:
        return Response(CACHE_INFO, media_type="text/x-nix-cache-info")

    @app.api_route("/nar/{name}", methods=["GET", "HEAD"])
    async def own_nar(name: str, request: Request) -> Response:
        if not cache_path_allowed(f"/nar/{name}"):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        query = f"?{request.url.query}" if request.url.query else ""
        return await stream(harmonia, f"/nar/{name}{query}", request)

    @app.api_route("/upstream/{index}/nar/{name}", methods=["GET", "HEAD"])
    async def upstream_nar(index: int, name: str, request: Request) -> Response:
        if not (0 <= index < len(upstreams) and cache_path_allowed(f"/nar/{name}")):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        return await stream(upstream_client, f"{upstreams[index].url}/nar/{name}", request)

    @app.api_route("/{name}", methods=["GET", "HEAD"])
    async def narinfo(name: str) -> Response:
        if not (name.endswith(".narinfo") and cache_path_allowed(f"/{name}")):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        try:
            own = await harmonia.get(f"/{name}")
        except httpx.HTTPError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Builder store unavailable") from exc
        if own.status_code == httpx.codes.OK:
            return Response(own.content, media_type="text/x-nix-narinfo")
        if own.status_code != httpx.codes.NOT_FOUND:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Builder store answered {own.status_code}")
        try:
            upstream = await upstream_narinfo(name)
        except _UpstreamError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        if upstream is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        return Response(upstream, media_type="text/x-nix-narinfo")

    return app
