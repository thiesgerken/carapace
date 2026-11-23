"""The session proxy refuses private and internal destinations unless the operator allows them."""

from __future__ import annotations

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


async def test_a_name_resolving_to_a_private_address_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, {"carapace-redis": ["10.43.12.7"]})
    with pytest.raises(DestinationRefusedError, match="CARAPACE_SANDBOX_PROXY_ALLOWED_NETWORKS"):
        await DestinationPolicy().resolve("carapace-redis", 6379)


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


@pytest.mark.parametrize("target", ["10.0.0.5:443", "[::1]:443", "carapace-builder:8330"])
async def test_connect_refuses_internal_targets_without_asking_the_sentinel(
    monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    fake_dns(monkeypatch, {"carapace-builder": ["10.43.99.1"]})
    approval = AsyncMock(return_value=BoundaryEvaluation(allowed=True, rejection=""))
    proxy = ProxyServer(
        verify_session_token=lambda _sid, _tok: True,
        get_allowed_domains=lambda _sid: {"*"},
        attach_sandbox_call=lambda _sid: contextlib.nullcontext(),
        request_approval=approval,
    )
    writer = _Writer()

    await proxy._handle_connect(AsyncMock(), writer, "s1", "10.0.0.2", target)  # type: ignore[arg-type]

    head, _, body = b"".join(writer.writes).partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 403")
    assert b"CARAPACE_SANDBOX_PROXY_ALLOWED_HOSTS" in body
    approval.assert_not_awaited()


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
