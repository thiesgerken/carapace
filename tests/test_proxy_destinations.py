"""The session proxy refuses private and internal destinations unless the operator allows them."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
from typing import Any
from unittest.mock import AsyncMock

import pytest

from carapace.sandbox.destinations import DestinationPolicy, DestinationRefusedError
from carapace.sandbox.proxy import ProxyServer
from carapace.security.context import BoundaryEvaluation
from tests.runtime_mocks import fake_dns

PUBLIC = "93.184.215.14"


@pytest.mark.parametrize(
    "address",
    [
        *("127.0.0.1", "10.43.0.10", "172.16.5.4", "192.168.178.20", "169.254.169.254", "100.64.0.1", "0.0.0.0"),
        *("::1", "fd00::5", "fe80::1", "::ffff:10.0.0.1"),
        # NAT64 and 6to4 reach the embedded IPv4; IPv4-compatible and site-local are deprecated forms.
        *("64:ff9b::a00:1", "64:ff9b::7f00:1", "2002:a00:1::1", "::10.0.0.1", "fec0::1"),
    ],
)
def test_internal_addresses_are_refused(address: str) -> None:
    assert DestinationPolicy().refuses(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", [PUBLIC, "2606:2800:21f:cb07:6820:80da:af6b:8b2c"])
def test_public_addresses_pass(address: str) -> None:
    assert not DestinationPolicy().refuses(ipaddress.ip_address(address))


def test_the_servers_own_addresses_are_refused_even_when_public() -> None:
    policy = DestinationPolicy(own_addresses=frozenset({ipaddress.ip_address(PUBLIC)}))
    assert policy.refuses(ipaddress.ip_address(PUBLIC))


def test_an_allowed_network_lifts_the_block() -> None:
    policy = DestinationPolicy(allowed_networks=(ipaddress.ip_network("192.168.178.0/24"),))
    assert not policy.refuses(ipaddress.ip_address("192.168.178.20"))
    assert policy.refuses(ipaddress.ip_address("192.168.1.20"))


def test_nat64_of_a_public_address_passes() -> None:
    assert not DestinationPolicy().refuses(ipaddress.ip_address("64:ff9b::5db8:d70e"))


async def test_a_name_resolving_to_a_private_address_is_refused_without_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_dns(monkeypatch, {"carapace-redis": ["10.43.12.7"]})
    with pytest.raises(DestinationRefusedError, match="CARAPACE_SANDBOX_PROXY_ALLOWED_NETWORKS") as refusal:
        await DestinationPolicy().resolve("carapace-redis", 6379)
    assert "10.43.12.7" not in str(refusal.value)


async def test_an_ip_literal_is_checked_without_a_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    lookups = fake_dns(monkeypatch, {})
    with pytest.raises(DestinationRefusedError):
        await DestinationPolicy().resolve("10.0.0.5", 443)
    assert lookups == []


async def test_one_private_answer_among_public_ones_refuses_the_name(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, {"rebind.example": [PUBLIC, "127.0.0.1"]})
    with pytest.raises(DestinationRefusedError):
        await DestinationPolicy().resolve("rebind.example", 443)


async def test_an_allowed_host_name_may_resolve_to_a_private_address(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, {"nas.home.arpa": ["192.168.178.5"]})
    policy = DestinationPolicy(allowed_hosts=frozenset({"nas.home.arpa"}))
    assert await policy.resolve("NAS.home.arpa", 443) == ["192.168.178.5"]


class _Writer:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None


def _proxy(approval: AsyncMock) -> ProxyServer:
    return ProxyServer(
        verify_session_token=lambda _sid, _tok: True,
        get_allowed_domains=lambda _sid: set(),
        attach_sandbox_call=lambda _sid: contextlib.nullcontext(),
        request_approval=approval,
    )


def _approval(allowed: bool) -> AsyncMock:
    return AsyncMock(return_value=BoundaryEvaluation(allowed=allowed, rejection="" if allowed else "Denied."))


def _refusal(writer: _Writer) -> bytes:
    head, _, body = b"".join(writer.writes).partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 403"), head
    return body


async def _connect(proxy: ProxyServer, target: str) -> _Writer:
    writer = _Writer()
    await proxy._handle_connect(AsyncMock(), writer, "s1", "10.0.0.2", target)  # type: ignore[arg-type]
    return writer


async def _get(proxy: ProxyServer, url: str) -> _Writer:
    writer = _Writer()
    await proxy._handle_http(AsyncMock(), writer, "s1", "10.0.0.2", "GET", url, "HTTP/1.1", [])  # type: ignore[arg-type]
    return writer


@pytest.mark.parametrize("target", ["10.0.0.5:443", "[::1]:443", "[64:ff9b::a00:1]:443"])
async def test_connect_refuses_internal_ip_literals_without_asking_anyone(
    monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    lookups = fake_dns(monkeypatch, {})
    approval = _approval(True)

    body = _refusal(await _connect(_proxy(approval), target))

    assert b"CARAPACE_SANDBOX_PROXY_ALLOWED_HOSTS" in body
    approval.assert_not_awaited()
    assert lookups == []


async def test_a_denied_name_is_never_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    lookups = fake_dns(monkeypatch, {"c2VjcmV0.evil.example": [PUBLIC]})

    body = _refusal(await _connect(_proxy(_approval(False)), "c2VjcmV0.evil.example:443"))

    assert body == b"Denied.\n"
    assert lookups == []


async def test_an_approved_name_resolving_internally_is_refused_without_the_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_dns(monkeypatch, {"carapace-builder": ["10.43.99.1"]})
    approval = _approval(True)

    body = _refusal(await _connect(_proxy(approval), "carapace-builder:8330"))

    approval.assert_awaited_once()
    assert b"CARAPACE_SANDBOX_PROXY_ALLOWED_NETWORKS" in body
    assert b"10.43.99.1" not in body


async def test_plain_http_refuses_an_internal_literal_without_asking(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, {})
    approval = _approval(True)

    _refusal(await _get(_proxy(approval), "http://10.0.0.1/admin"))

    approval.assert_not_awaited()


async def test_plain_http_refuses_an_approved_name_resolving_internally(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, {"redis.internal.example": ["10.43.0.9"]})

    body = _refusal(await _get(_proxy(_approval(True)), "http://redis.internal.example/"))

    assert b"10.43.0.9" not in body


async def test_connect_dials_the_checked_address(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, {"pypi.org": [PUBLIC]})
    dialed: list[tuple[str, int]] = []

    async def open_connection(host: str, port: int, **_kwargs: Any) -> Any:
        dialed.append((host, port))
        raise OSError("stop here")

    monkeypatch.setattr("carapace.sandbox.proxy.asyncio.open_connection", open_connection)
    proxy = ProxyServer(
        verify_session_token=lambda _sid, _tok: True,
        get_allowed_domains=lambda _sid: {"pypi.org"},
        attach_sandbox_call=lambda _sid: contextlib.nullcontext(),
    )

    await proxy._handle_connect(AsyncMock(), _Writer(), "s1", "10.0.0.2", "pypi.org:443")  # type: ignore[arg-type]

    assert dialed == [(PUBLIC, 443)]


NARINFO = "/0z5c0imb0fnaf9a3ab2s1a39xh1g8gqi.narinfo"


def _cache_proxy(approval: AsyncMock, cache_url: str | None = "http://builder:8331") -> ProxyServer:
    return ProxyServer(
        verify_session_token=lambda _sid, _tok: True,
        get_allowed_domains=lambda _sid: set(),
        attach_sandbox_call=lambda _sid: contextlib.nullcontext(),
        request_approval=approval,
        builder_cache_url=cache_url,
    )


async def test_the_builder_cache_is_forwarded_without_a_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    lookups = fake_dns(monkeypatch, {})
    remote = _Writer()
    dialed: list[tuple[str, int]] = []

    async def open_connection(host: str, port: int, **_kwargs: Any) -> Any:
        dialed.append((host, port))
        response = asyncio.StreamReader()
        response.feed_data(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        response.feed_eof()
        return response, remote

    monkeypatch.setattr("carapace.sandbox.proxy.asyncio.open_connection", open_connection)
    approval = _approval(False)
    writer = _Writer()
    await _cache_proxy(approval)._handle_http(
        AsyncMock(),
        writer,  # type: ignore[arg-type]
        "s1",
        "10.0.0.2",
        "GET",
        f"http://cache.carapace.internal{NARINFO}",
        "HTTP/1.1",
        [b"Host: cache.carapace.internal"],
    )

    request = b"".join(remote.writes)
    assert dialed == [("builder", 8331)]
    assert request.startswith(f"GET {NARINFO} HTTP/1.1\r\n".encode())
    assert b"Host: builder:8331\r\n" in request and b"cache.carapace.internal" not in request
    assert b"".join(writer.writes).endswith(b"ok")
    approval.assert_not_awaited()
    assert lookups == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/builds/0123"),
        ("GET", "/info"),
        ("GET", "/nar/../builds"),
        ("GET", "/upstream/0/builds"),
        ("PUT", NARINFO),
        ("POST", "/nar/1abc.nar.xz"),
    ],
)
async def test_the_builder_cache_mapping_passes_only_cache_reads(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    async def open_connection(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("must not connect")

    monkeypatch.setattr("carapace.sandbox.proxy.asyncio.open_connection", open_connection)
    approval = _approval(True)
    writer = _Writer()
    await _cache_proxy(approval)._handle_http(
        AsyncMock(),
        writer,  # type: ignore[arg-type]
        "s1",
        "10.0.0.2",
        method,
        f"http://cache.carapace.internal{path}",
        "HTTP/1.1",
        [],
    )

    assert b"serves only reads" in _refusal(writer)
    approval.assert_not_awaited()


async def test_the_builder_cache_is_unavailable_without_a_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, {})
    approval = _approval(True)

    body = _refusal(await _get(_cache_proxy(approval, None), f"http://cache.carapace.internal{NARINFO}"))

    assert b"No builder cache" in body
    approval.assert_not_awaited()


async def test_the_builder_cache_refuses_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, {})
    approval = _approval(True)

    _refusal(await _connect(_cache_proxy(approval), "cache.carapace.internal:443"))

    approval.assert_not_awaited()
