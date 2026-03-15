"""Unit tests for KubernetesRuntime — mock all K8s API calls."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _ns_factory(**defaults):
    """Create a callable that returns a SimpleNamespace with given kwargs."""

    def factory(**kwargs):
        merged = {**defaults, **kwargs}
        return SimpleNamespace(**merged)

    return factory


# Mock the kubernetes package before importing KubernetesRuntime.
# Use force-set (not setdefault) in case a previous test run cached stale mocks.
_mock_k8s_client = MagicMock()
_mock_k8s_config = MagicMock()
_mock_k8s_stream = MagicMock()
_mock_k8s_top = MagicMock()

# Wire up `from kubernetes import client` → our custom mock
_mock_k8s_top.client = _mock_k8s_client
_mock_k8s_top.config = _mock_k8s_config

# Replace model constructors with SimpleNamespace factories so tests can
# inspect constructed objects by attribute access.
_mock_k8s_client.V1Pod = _ns_factory()
_mock_k8s_client.V1PodSpec = _ns_factory()
_mock_k8s_client.V1Container = _ns_factory()
_mock_k8s_client.V1ObjectMeta = _ns_factory()
_mock_k8s_client.V1Volume = _ns_factory()
_mock_k8s_client.V1VolumeMount = _ns_factory()
_mock_k8s_client.V1EnvVar = _ns_factory()
_mock_k8s_client.V1SecurityContext = _ns_factory()
_mock_k8s_client.V1Capabilities = _ns_factory()
_mock_k8s_client.V1PersistentVolumeClaimVolumeSource = _ns_factory()
_mock_k8s_client.V1OwnerReference = _ns_factory()
_mock_k8s_client.CoreV1Api = MagicMock
_mock_k8s_client.AppsV1Api = MagicMock

sys.modules["kubernetes"] = _mock_k8s_top
sys.modules["kubernetes.client"] = _mock_k8s_client
sys.modules["kubernetes.config"] = _mock_k8s_config
sys.modules["kubernetes.stream"] = _mock_k8s_stream
sys.modules["kubernetes.client.rest"] = MagicMock()


# Provide real exception class on the mocked module
def _make_api_exception(status: int = 500, reason: str = "") -> Exception:
    exc = Exception(reason)
    exc.status = status  # type: ignore[attr-defined]
    exc.reason = reason  # type: ignore[attr-defined]
    return exc


_ApiException = type("ApiException", (Exception,), {})


def _api_exc_init(self: Exception, status: int = 500, reason: str = "") -> None:
    super(_ApiException, self).__init__(reason)
    self.status = status  # type: ignore[attr-defined]
    self.reason = reason  # type: ignore[attr-defined]


_ApiException.__init__ = _api_exc_init  # type: ignore[assignment]
_mock_k8s_client.ApiException = _ApiException

# Force reimport so the module picks up our stub constructors
sys.modules.pop("carapace.sandbox.kubernetes", None)

from carapace.sandbox.kubernetes import KubernetesRuntime, _sanitize_pod_name  # noqa: E402
from carapace.sandbox.runtime import ContainerConfig, Mount  # noqa: E402

# --- Helpers ---


def _make_runtime(*, namespace: str = "carapace", data_dir: str = "/data") -> KubernetesRuntime:
    """Build a KubernetesRuntime with mocked K8s clients."""
    with patch.object(KubernetesRuntime, "__init__", lambda self, **kw: None):
        rt = KubernetesRuntime.__new__(KubernetesRuntime)
    rt._core = MagicMock()
    rt._apps = MagicMock()
    rt._namespace = namespace
    rt._pvc_claim = "carapace-data"
    rt._data_dir = Path(data_dir)
    rt._service_account = None
    rt._priority_class = None
    rt._owner_ref = None
    rt._app_instance = "carapace"
    return rt


# --- _sanitize_pod_name ---


def test_sanitize_pod_name_basic():
    assert _sanitize_pod_name("carapace-session-abc") == "carapace-session-abc"


def test_sanitize_pod_name_underscore():
    assert _sanitize_pod_name("carapace_session_abc") == "carapace-session-abc"


def test_sanitize_pod_name_truncate():
    long_name = "a" * 100
    assert len(_sanitize_pod_name(long_name)) == 63


def test_sanitize_pod_name_strips_hyphens():
    assert _sanitize_pod_name("--abc--") == "abc"


# --- _mount_to_subpath ---


def test_mount_to_subpath():
    rt = _make_runtime(data_dir="/data")
    mount = Mount(source="/data/memory", target="/workspace/memory", read_only=True)
    assert rt._mount_to_subpath(mount) == "memory"


def test_mount_to_subpath_nested():
    rt = _make_runtime(data_dir="/data")
    mount = Mount(source="/data/sessions/abc/workspace/skills", target="/workspace/skills")
    assert rt._mount_to_subpath(mount) == "sessions/abc/workspace/skills"


def test_mount_to_subpath_outside_data_dir():
    rt = _make_runtime(data_dir="/data")
    mount = Mount(source="/other/path", target="/workspace/other")
    assert rt._mount_to_subpath(mount) == "/other/path"


# --- _build_pod_spec ---


def test_build_pod_spec_basic():
    rt = _make_runtime()
    config = ContainerConfig(
        image="sandbox:latest",
        name="carapace-sandbox-test123",
        labels={"carapace.session": "test123"},
        mounts=[
            Mount(source="/data/memory", target="/workspace/memory", read_only=True),
            Mount(source="/data/sessions/s1/workspace/skills", target="/workspace/skills"),
        ],
        network="carapace-sandbox",
        command=["sleep", "infinity"],
        environment={"HTTP_PROXY": "http://proxy:3128"},
    )
    pod = rt._build_pod_spec(config)
    assert pod.metadata is not None
    assert pod.spec is not None
    assert pod.metadata.name == "carapace-sandbox-test123"
    assert pod.metadata.namespace == "carapace"
    assert pod.spec.containers[0].image == "sandbox:latest"
    assert pod.spec.containers[0].command == ["sleep", "infinity"]
    assert pod.spec.restart_policy == "Always"
    assert pod.spec.automount_service_account_token is False

    # Standard labels should be merged with config labels
    labels = pod.metadata.labels
    assert labels["app"] == "carapace-sandbox"
    assert labels["app.kubernetes.io/component"] == "sandbox"
    assert labels["carapace.session"] == "test123"

    # Volume mounts should use subPath from PVC
    vmounts = pod.spec.containers[0].volume_mounts
    assert len(vmounts) == 2
    assert vmounts[0].sub_path == "memory"
    assert vmounts[0].read_only is True
    assert vmounts[1].sub_path == "sessions/s1/workspace/skills"

    # Single PVC volume
    assert len(pod.spec.volumes) == 1
    assert pod.spec.volumes[0].persistent_volume_claim.claim_name == "carapace-data"


def test_build_pod_spec_string_command():
    rt = _make_runtime()
    config = ContainerConfig(
        image="sandbox:latest",
        name="test",
        network=None,
        command="echo hello",
    )
    pod = rt._build_pod_spec(config)
    assert pod.spec is not None
    assert pod.spec.containers[0].command == ["bash", "-c", "echo hello"]


def test_build_pod_spec_no_command():
    rt = _make_runtime()
    config = ContainerConfig(
        image="sandbox:latest",
        name="test",
        network=None,
    )
    pod = rt._build_pod_spec(config)
    assert pod.spec is not None
    assert pod.spec.containers[0].command == ["sh", "-c", "echo 'carapace sandbox ready' && exec sleep infinity"]


def test_build_pod_spec_security_context():
    rt = _make_runtime()
    config = ContainerConfig(image="sandbox:latest", name="test", network=None)
    pod = rt._build_pod_spec(config)
    assert pod.spec is not None
    sc = pod.spec.containers[0].security_context
    assert sc.run_as_non_root is True
    assert sc.run_as_user == 1000
    assert sc.allow_privilege_escalation is False


# --- create ---


async def test_create_calls_api():
    rt = _make_runtime()
    rt._core.read_namespaced_pod.return_value = SimpleNamespace(status=SimpleNamespace(phase="Running"))

    config = ContainerConfig(
        image="sandbox:latest",
        name="carapace-sandbox-abc",
        network="carapace-sandbox",
        command=["sleep", "infinity"],
    )
    container_id = await rt.create(config)
    assert container_id == "carapace-sandbox-abc"
    rt._core.create_namespaced_pod.assert_called_once()


# --- is_running ---


async def test_is_running_true():
    rt = _make_runtime()
    rt._core.read_namespaced_pod.return_value = SimpleNamespace(status=SimpleNamespace(phase="Running"))
    assert await rt.is_running("test-pod") is True


async def test_is_running_false():
    rt = _make_runtime()
    rt._core.read_namespaced_pod.return_value = SimpleNamespace(status=SimpleNamespace(phase="Pending"))
    assert await rt.is_running("test-pod") is False


# --- get_ip ---


async def test_get_ip():
    rt = _make_runtime()
    rt._core.read_namespaced_pod.return_value = SimpleNamespace(status=SimpleNamespace(pod_ip="10.42.0.5"))
    ip = await rt.get_ip("test-pod", "any-network")
    assert ip == "10.42.0.5"


# --- remove ---


async def test_remove():
    rt = _make_runtime()
    await rt.remove("test-pod")
    rt._core.delete_namespaced_pod.assert_called_once_with(
        name="test-pod", namespace="carapace", grace_period_seconds=0
    )


# --- resolve_self_network_name ---


async def test_resolve_self_network_name_noop():
    rt = _make_runtime()
    assert await rt.resolve_self_network_name("carapace-sandbox") == "carapace-sandbox"


# --- image_exists ---


def test_image_exists_always_true():
    rt = _make_runtime()
    assert rt.image_exists("any:tag") is True


# --- get_host_ip ---


async def test_get_host_ip_from_env(monkeypatch):
    rt = _make_runtime()
    monkeypatch.setenv("CARAPACE_SERVICE_HOST", "10.43.0.100")
    ip = await rt.get_host_ip("any-network")
    assert ip == "10.43.0.100"
