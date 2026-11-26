"""Start-up self-test: a sandbox must not reach the internet or resolve names except through its session proxy.

Without `exec` review the network boundary is the only layer, and it is easy to lose silently: a Kubernetes
CNI that ignores NetworkPolicy, a namespace policy that lets pods reach the cluster DNS, or a Docker sandbox
network that is not internal.
"""

from __future__ import annotations

import ipaddress

from .runtime import ExecResult

# Public resolvers' anycast addresses: reachable from nearly every network that has egress at all.
# ponytail: fixed targets, a network that blocks exactly these but nothing else passes the check.
_PUBLIC_TARGETS = ("1.1.1.1/443", "8.8.8.8/53", "9.9.9.9/443")

_DOCS = "See docs/security.md, section 'Start-up egress self-test'."

# Runs as the sandbox's own process without proxy variables. Prints one line per leak, nothing when sealed.
# The session proxy at PROXY_TARGET must answer, or the probe cannot tell sealed from broken. A request without
# credentials, whose 407 only the proxy itself sends: a relay in between accepts the connection even when it
# cannot reach the server, so a TCP handshake alone proves nothing.
# `timeout` matters: a NetworkPolicy drops packets, so an unguarded connect would hang for minutes.
PROBE_SCRIPT = f"""\
for tool in timeout getent head; do
    command -v "$tool" >/dev/null || {{ echo "missing $tool in the sandbox image" >&2; exit 1; }}
done
status=$(timeout 5 bash -c "exec 3<>/dev/tcp/$PROXY_TARGET && \\
    printf 'GET http://egress-check.invalid/ HTTP/1.1\\r\\nHost: egress-check.invalid\\r\\n\\r\\n' >&3 && \\
    head -n 1 <&3" 2>/dev/null)
if [[ $status != "HTTP/1."?" 407 "* ]]; then
    echo "positive control failed: the session proxy at ${{PROXY_TARGET/\\//:}} did not answer \\
(got: ${{status:-nothing}})" >&2
    exit 1
fi
for target in {" ".join(_PUBLIC_TARGETS)} $DNS_TARGETS; do
    if timeout 5 bash -c "exec 3<>/dev/tcp/$target" 2>/dev/null; then
        echo "direct TCP connection to ${{target/\\//:}} succeeded"
    fi
done
if timeout 5 getent hosts example.com >/dev/null 2>&1; then
    echo "DNS lookup of example.com succeeded"
fi
"""


class EgressCheckError(RuntimeError):
    """A sandbox reached the network past its session proxy."""

    def __init__(self, leaks: list[str]) -> None:
        super().__init__("; ".join(leaks))
        self.leaks = leaks


class EgressProbeError(RuntimeError):
    """The probe could not run, so nothing is known about the boundary."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"Sandbox egress self-test could not run, so carapace cannot tell whether sandboxes are sealed: "
            f"{reason}. {_DOCS}"
        )


def probe_env(proxy_host: str, proxy_port: int, resolv_conf: str) -> dict[str, str]:
    """The probe's inputs: the session proxy as the positive control, and the server's resolvers to test.

    On Kubernetes the server resolves through the cluster DNS, which a namespace policy often opens to every
    pod. Loopback resolvers (Docker's embedded one) are the sandbox's own, which `getent` covers.
    """
    nameservers = [
        fields[1] for line in resolv_conf.splitlines() if len(fields := line.split()) >= 2 and fields[0] == "nameserver"
    ]
    dns_targets = [f"{ip}/53" for ip in nameservers if not ipaddress.ip_address(ip.split("%")[0]).is_loopback]
    return {"PROXY_TARGET": f"{proxy_host}/{proxy_port}", "DNS_TARGETS": " ".join(dns_targets)}


def raise_for_leaks(result: ExecResult) -> None:
    """Fail loudly on a probe that could not run, and raise ``EgressCheckError`` for every leak it found."""
    if result.exit_code != 0:
        raise EgressProbeError(result.output.strip() or f"exit status {result.exit_code}")
    leaks = result.stdout.splitlines()
    if leaks:
        raise EgressCheckError(leaks)
