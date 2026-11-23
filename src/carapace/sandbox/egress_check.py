"""Start-up self-test: a sandbox must not reach the internet or resolve names except through its session proxy.

Without `exec` review the network boundary is the only layer, and it is easy to lose silently: a Kubernetes
CNI that ignores NetworkPolicy, or a Docker sandbox network that is not internal.
"""

from __future__ import annotations

from .runtime import ExecResult

# Public resolvers' anycast addresses: reachable from nearly every network that has egress at all.
# ponytail: fixed targets, a network that blocks exactly these but nothing else passes the check.
_TCP_TARGETS = ("1.1.1.1/443", "8.8.8.8/53", "9.9.9.9/443")

# Runs as the sandbox's own process without proxy variables. Prints one line per leak, nothing when sealed.
# `timeout` matters: a NetworkPolicy drops packets, so an unguarded connect would hang for minutes.
PROBE_SCRIPT = f"""\
for tool in timeout getent; do
    command -v "$tool" >/dev/null || {{ echo "missing $tool in the sandbox image" >&2; exit 1; }}
done
for target in {" ".join(_TCP_TARGETS)}; do
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


def raise_for_leaks(result: ExecResult) -> None:
    """Fail loudly on a probe that could not run, and raise ``EgressCheckError`` for every leak it found."""
    if result.exit_code != 0:
        raise RuntimeError(f"Sandbox egress self-test could not run: {result.output.strip()}")
    leaks = result.stdout.splitlines()
    if leaks:
        raise EgressCheckError(leaks)
