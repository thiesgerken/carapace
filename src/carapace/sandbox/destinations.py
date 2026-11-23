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

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
type IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


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
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        if any(address in network for network in self.allowed_networks):
            return False
        # Not global covers loopback, RFC 1918, link-local, unique-local, CGNAT and reserved ranges.
        return address in self.own_addresses or not address.is_global

    async def resolve(self, host: str, port: int) -> list[str]:
        """Resolve *host* and return its addresses, each one checked, to connect to directly.

        Connecting to these instead of the name means a second DNS answer cannot swap in an
        internal address after the check. Raises if any address is refused.
        """
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(ipaddress.ip_address(info[4][0]) for info in infos))
        if host.lower() not in self.allowed_hosts:
            refused = [address for address in addresses if self.refuses(address)]
            if refused:
                raise DestinationRefusedError(
                    f"{host} resolves to {refused[0]}, a private or internal address. The proxy does not "
                    "connect sandboxes to internal destinations unless an operator allows them with "
                    "CARAPACE_SANDBOX_PROXY_ALLOWED_NETWORKS (CIDRs) or CARAPACE_SANDBOX_PROXY_ALLOWED_HOSTS "
                    "(exact host names)."
                )
        return [str(address) for address in addresses]
