"""TCP tunnels a command asked for with ``cgate request --tunnel``, open until its exec ends.

The client keeps the original host name. /etc/hosts maps it to a loopback address of its own, where
``carapace-tunnel`` listens on the tunnel's port and forwards each connection with CONNECT through the session
proxy. One address per host lets two hosts share a port. The proxy checks the host like any domain: the
approval that opened the tunnel granted it for the exec.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

TUNNEL_DIR = "/tmp/carapace-tunnels"
_HOSTS_BACKUP = f"{TUNNEL_DIR}/hosts"
# By absolute path: the agent can write to the directories on PATH.
_FORWARDER = "/bin/carapace-tunnel"
# An exact host name; a wildcard has no address to listen on.
_TUNNEL = re.compile(r"([a-z0-9-]+(?:\.[a-z0-9-]+)*):([0-9]{1,5})")
_READY_SECONDS = 10


@dataclass(frozen=True, order=True, slots=True)
class Tunnel:
    host: str
    port: int

    def __str__(self) -> str:
        return f"{self.host}:{self.port}"


def parse_tunnel(raw: str) -> Tunnel | None:
    """A ``HOST:PORT`` as ``cgate`` sends it, or None when it is not one."""
    match = _TUNNEL.fullmatch(raw.strip().lower())
    if match is None or not 1 <= int(match.group(2)) <= 65535:
        return None
    return Tunnel(match.group(1), int(match.group(2)))


def listen_addresses(opened: dict[Tunnel, str], new: list[Tunnel]) -> dict[Tunnel, str]:
    """A loopback address for each new tunnel: its host's existing one, or the next free one."""
    by_host = {tunnel.host: address for tunnel, address in opened.items()}
    for tunnel in new:
        by_host.setdefault(tunnel.host, f"127.0.0.{len(by_host) + 2}")
    if len(by_host) > 250:
        raise ValueError("an exec cannot tunnel to more than 250 hosts")
    return {tunnel: by_host[tunnel.host] for tunnel in new}


def open_script(new: dict[Tunnel, str], opened: dict[Tunnel, str]) -> str:
    """Shadow the new hosts in /etc/hosts and start a forwarder per tunnel; fails if one does not come up."""
    known = {tunnel.host for tunnel in opened}
    host_lines = sorted({f"{address} {tunnel.host}" for tunnel, address in new.items() if tunnel.host not in known})
    lines = [
        "set -e",
        f"mkdir -p {TUNNEL_DIR}",
        # The first tunnel of an exec keeps the original, which the close script puts back.
        f"[ -f {_HOSTS_BACKUP} ] || cp /etc/hosts {_HOSTS_BACKUP}",
        *(f"echo {shlex.quote(line)} >> /etc/hosts" for line in host_lines),
    ]
    for index, (tunnel, address) in enumerate(sorted(new.items()), start=len(opened)):
        base = f"{TUNNEL_DIR}/{index}"
        listen = shlex.quote(f"{address}:{tunnel.port}")
        lines.append(
            f"nohup {_FORWARDER} {listen} {shlex.quote(str(tunnel))} {base}.ready > {base}.log 2>&1 &"
            f" echo $! > {base}.pid"
        )
        lines.append(
            f"for _ in $(seq {_READY_SECONDS * 10}); do [ -f {base}.ready ] && break;"
            f' kill -0 "$(cat {base}.pid)" 2>/dev/null || break; sleep 0.1; done'
        )
        lines.append(f'[ -f {base}.ready ] || {{ echo "{tunnel} did not start:"; cat {base}.log; exit 1; }}')
    return "\n".join(lines) + "\n"


def close_script() -> str:
    """Stop every forwarder of the exec and put /etc/hosts back."""
    return (
        f'for pid in {TUNNEL_DIR}/*.pid; do [ -f "$pid" ] && kill "$(cat "$pid")" 2>/dev/null; done\n'
        f"[ ! -f {_HOSTS_BACKUP} ] || cp {_HOSTS_BACKUP} /etc/hosts\n"
        f"rm -rf {TUNNEL_DIR}\n"
    )
