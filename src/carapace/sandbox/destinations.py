"""Which addresses the session proxy may connect a sandbox to.

The proxy connects from the server's network position, where cluster services, the Compose
network and the operator's LAN are reachable, some without authentication. A domain approval
must not open those, so internal addresses are refused before the sentinel is asked, unless the
operator allowed them.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass

from loguru import logger

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
type IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_IPV4_COMPATIBLE = ipaddress.ip_network("::/96")


def ip_literal(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _embedded_ipv4(address: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv6 address stands for (mapped, NAT64, 6to4), which is what gets reached."""
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address.sixtofour is not None:
        return address.sixtofour
    if address in _NAT64:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return None


class DestinationRefusedError(Exception):
    pass


@dataclass(frozen=True)
class DestinationPolicy:
    # Operator-allowed despite being internal: CIDRs, and host names matched exactly.
    allowed_networks: tuple[IPNetwork, ...] = ()
    allowed_hosts: frozenset[str] = frozenset()
    # The server's own addresses and the Kubernetes API's, refused even where they are public.
    own_addresses: frozenset[IPAddress] = frozenset()

    def refuses(self, address: IPAddress) -> bool:
        if isinstance(address, ipaddress.IPv6Address):
            if (embedded := _embedded_ipv4(address)) is not None:
                address = embedded
            # Deprecated forms that is_global misses: IPv4-compatible (::a.b.c.d) and site-local.
            elif address in _IPV4_COMPATIBLE or address.is_site_local:
                return not any(address in network for network in self.allowed_networks)
        if any(address in network for network in self.allowed_networks):
            return False
        # Not global covers loopback, RFC 1918, link-local, unique-local, CGNAT and reserved ranges.
        return address in self.own_addresses or not address.is_global

    async def resolve(self, host: str, port: int) -> list[str]:
        """Resolve *host* and return its addresses, each one checked, to connect to directly.

        Connecting to these instead of the name means a second DNS answer cannot swap in an
        internal address after the check. Raises if any address is refused. An IP literal is
        checked as it is, without a lookup. A name is looked up, so call this only for a name the
        session may reach: the lookup itself carries the name out through the server's resolver.
        """
        if (literal := ip_literal(host)) is not None:
            addresses = [literal]
        else:
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
            addresses = list(dict.fromkeys(ipaddress.ip_address(info[4][0]) for info in infos))
        if host.lower() not in self.allowed_hosts:
            refused = [address for address in addresses if self.refuses(address)]
            if refused:
                # The address stays in the server log; the sandbox must not learn internal addresses.
                logger.warning(f"Proxy: {host} resolves to the internal address {refused[0]}")
                raise DestinationRefusedError(
                    f"{host} is a private or internal address or resolves to one. The proxy does not "
                    "connect sandboxes to internal destinations unless an operator allows them with "
                    "CARAPACE_SANDBOX_PROXY_ALLOWED_NETWORKS (CIDRs) or CARAPACE_SANDBOX_PROXY_ALLOWED_HOSTS "
                    "(exact host names); in the Helm chart sandbox.allowedInternalNetworks and "
                    "sandbox.allowedInternalHosts."
                )
        return [str(address) for address in addresses]
