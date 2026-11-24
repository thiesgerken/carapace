"""Every pod outside the builder namespace passes Pod Security level `baseline`.

The release namespace can then enforce `baseline` (docs/kubernetes.md). The checks follow the
baseline controls of https://kubernetes.io/docs/concepts/security/pod-security-standards/.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from carapace.sandbox.runtime import ContainerConfig, SandboxConfig
from tests.test_kubernetes import _make_runtime

_CHART = Path(__file__).parent.parent / "charts" / "carapace"
_RELEASE_NAMESPACE = "carapace"

_BASELINE_CAPABILITIES = {
    "AUDIT_WRITE",
    "CHOWN",
    "DAC_OVERRIDE",
    "FOWNER",
    "FSETID",
    "KILL",
    "MKNOD",
    "NET_BIND_SERVICE",
    "SETFCAP",
    "SETGID",
    "SETPCAP",
    "SETUID",
    "SYS_CHROOT",
}
_SAFE_SYSCTLS = {
    "kernel.shm_rmid_forced",
    "net.ipv4.ip_local_port_range",
    "net.ipv4.ip_unprivileged_port_start",
    "net.ipv4.tcp_syncookies",
    "net.ipv4.ping_group_range",
    "net.ipv4.ip_local_reserved_ports",
    "net.ipv4.tcp_keepalive_time",
    "net.ipv4.tcp_fin_timeout",
    "net.ipv4.tcp_keepalive_intvl",
    "net.ipv4.tcp_keepalive_probes",
}
_SELINUX_TYPES = {"", "container_t", "container_init_t", "container_kvm_t", "container_engine_t"}


def _security_context_violations(where: str, ctx: dict) -> list[str]:
    violations = []
    if ctx.get("privileged"):
        violations.append(f"{where}: privileged")
    if ctx.get("windowsOptions", {}).get("hostProcess"):
        violations.append(f"{where}: hostProcess")
    if added := set(ctx.get("capabilities", {}).get("add", [])) - _BASELINE_CAPABILITIES:
        violations.append(f"{where}: adds capabilities {sorted(added)}")
    if ctx.get("procMount", "Default") != "Default":
        violations.append(f"{where}: procMount {ctx['procMount']}")
    if ctx.get("seccompProfile", {}).get("type") == "Unconfined":
        violations.append(f"{where}: seccomp Unconfined")
    if ctx.get("appArmorProfile", {}).get("type") == "Unconfined":
        violations.append(f"{where}: AppArmor Unconfined")
    selinux = ctx.get("seLinuxOptions", {})
    if selinux.get("type", "") not in _SELINUX_TYPES or "user" in selinux or "role" in selinux:
        violations.append(f"{where}: seLinuxOptions {selinux}")
    return violations


def _baseline_violations(name: str, pod: dict) -> list[str]:
    """Baseline violations of a pod template (metadata + spec)."""
    spec = pod["spec"]
    violations = [f"{name}: {field}" for field in ("hostNetwork", "hostPID", "hostIPC") if spec.get(field)]
    violations += [f"{name}: hostPath volume {v['name']}" for v in spec.get("volumes", []) if "hostPath" in v]
    pod_ctx = spec.get("securityContext", {})
    violations += _security_context_violations(name, pod_ctx)
    if unsafe := {s["name"] for s in pod_ctx.get("sysctls", [])} - _SAFE_SYSCTLS:
        violations.append(f"{name}: sysctls {sorted(unsafe)}")
    for annotation, profile in pod.get("metadata", {}).get("annotations", {}).items():
        if annotation.startswith("container.apparmor.security.beta.kubernetes.io/") and profile == "unconfined":
            violations.append(f"{name}: {annotation}")
    containers = [*spec.get("initContainers", []), *spec["containers"], *spec.get("ephemeralContainers", [])]
    for container in containers:
        where = f"{name}/{container['name']}"
        violations += _security_context_violations(where, container.get("securityContext", {}))
        violations += [f"{where}: hostPort {p['hostPort']}" for p in container.get("ports", []) if p.get("hostPort")]
    return violations


def _render_chart() -> list[dict]:
    rendered = subprocess.run(
        [
            "helm",
            "template",
            "carapace",
            str(_CHART),
            "--namespace",
            _RELEASE_NAMESPACE,
            "--set",
            "postgres.image.tag=19-alpine",
            "--set",
            "bitwarden.instances[0].name=demo",
            "--set",
            "bitwarden.instances[0].basicAuth.existingSecret=demo",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [doc for doc in yaml.safe_load_all(rendered) if doc]


def _chart_pods(namespace: str) -> dict[str, dict]:
    return {
        f"{doc['kind']}/{doc['metadata']['name']}": doc["spec"]["template"]
        for doc in _render_chart()
        if "template" in doc.get("spec", {}) and doc["metadata"].get("namespace", _RELEASE_NAMESPACE) == namespace
    }


def test_release_namespace_pods_pass_baseline():
    pods = _chart_pods(_RELEASE_NAMESPACE)
    assert "Deployment/carapace" in pods
    assert [v for name, pod in pods.items() for v in _baseline_violations(name, pod)] == []


def test_sandbox_pods_pass_baseline():
    runtime = _make_runtime()
    pod = runtime._build_pod_dict(ContainerConfig(image="sandbox:latest", name="demo", network=None))
    sts = runtime._build_statefulset_dict(
        SandboxConfig(name="carapace-sandbox-demo", sandbox_id="demo", session_id="demo", image="sandbox:latest")
    )
    assert _baseline_violations("pod", pod) + _baseline_violations("statefulset", sts["spec"]["template"]) == []


def test_builder_gets_its_own_privileged_namespace():
    namespace = next(doc for doc in _render_chart() if doc["kind"] == "Namespace")
    assert namespace["metadata"]["name"] == f"{_RELEASE_NAMESPACE}-builder"
    assert namespace["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "privileged"
    assert namespace["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"
    # Proves the checker catches what baseline rejects, so the tests above are not vacuous.
    builder = _chart_pods(f"{_RELEASE_NAMESPACE}-builder")
    assert _baseline_violations("builder", builder["Deployment/carapace-builder"])
