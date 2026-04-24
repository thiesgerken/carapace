"""Unit tests for KubernetesRuntime — mock all kr8s API calls."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import kr8s
import pytest

from carapace.sandbox.kubernetes import (
    KubernetesRuntime,
    _default_command,
    _Sandboxes,
    _sanitize_pod_name,
    _standard_labels,
)
from carapace.sandbox.runtime import ContainerConfig, ExecResult, Mount, SandboxConfig

# --- Helpers ---


def _make_runtime(*, namespace: str = "carapace", data_dir: str = "/data") -> KubernetesRuntime:
    """Build a KubernetesRuntime without triggering __init__ side effects."""
    with patch.object(KubernetesRuntime, "__init__", lambda self, **kw: None):
        rt = KubernetesRuntime.__new__(KubernetesRuntime)
    rt._namespace = namespace
    rt._pvc_claim = "carapace-data"
    rt._data_dir = Path(data_dir)
    rt._service_account = None
    rt._priority_class = None
    rt._app_instance = "carapace"
    rt._session_pvc_size = "1Gi"
    rt._session_pvc_storage_class = None
    rt._resource_spec = None
    rt._want_owner_ref = False
    rt._server_deployment_name = "carapace"
    rt._sandboxes_name = "carapace-sandboxes"
    rt._sandbox_owner = None
    rt._sandbox_owner_lookup_done = False
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


# --- _default_command ---


def test_default_command_none():
    assert _default_command(None) == ["sh", "-c", "echo 'carapace sandbox ready' && exec sleep infinity"]


def test_default_command_string():
    assert _default_command("echo hello") == ["bash", "-c", "echo hello"]


def test_default_command_list():
    assert _default_command(["sleep", "infinity"]) == ["sleep", "infinity"]


# --- _standard_labels ---


def test_standard_labels():
    labels = _standard_labels("carapace")
    assert labels["app"] == "carapace-sandbox"
    assert labels["app.kubernetes.io/component"] == "sandbox"
    assert labels["app.kubernetes.io/managed-by"] == "carapace-server"


def test_sandboxes_kr8s_plural_matches_crd():
    """kr8s defaults plural to kind.lower() + 's', which yields sandboxess for kind Sandboxes."""
    assert _Sandboxes.plural == "sandboxes"
    assert _Sandboxes.endpoint == "sandboxes"


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


# --- _build_pod_dict ---


def test_build_pod_dict_basic():
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
    pod = rt._build_pod_dict(config)

    assert pod["metadata"]["name"] == "carapace-sandbox-test123"
    assert pod["metadata"]["namespace"] == "carapace"

    container = pod["spec"]["containers"][0]
    assert container["image"] == "sandbox:latest"
    assert container["command"] == ["sleep", "infinity"]

    assert pod["spec"]["restartPolicy"] == "Always"
    assert pod["spec"]["automountServiceAccountToken"] is False

    # Standard labels merged with config labels
    labels = pod["metadata"]["labels"]
    assert labels["app"] == "carapace-sandbox"
    assert labels["app.kubernetes.io/component"] == "sandbox"
    assert labels["carapace.session"] == "test123"

    # Volume mounts use subPath from PVC
    vmounts = container["volumeMounts"]
    assert len(vmounts) == 2
    assert vmounts[0]["subPath"] == "memory"
    assert vmounts[0].get("readOnly") is True
    assert vmounts[1]["subPath"] == "sessions/s1/workspace/skills"

    # Single PVC volume
    volumes = pod["spec"]["volumes"]
    assert len(volumes) == 1
    assert volumes[0]["persistentVolumeClaim"]["claimName"] == "carapace-data"


def test_build_pod_dict_string_command():
    rt = _make_runtime()
    config = ContainerConfig(
        image="sandbox:latest",
        name="test",
        network=None,
        command="echo hello",
    )
    pod = rt._build_pod_dict(config)
    assert pod["spec"]["containers"][0]["command"] == ["bash", "-c", "echo hello"]


def test_build_pod_dict_no_command():
    rt = _make_runtime()
    config = ContainerConfig(
        image="sandbox:latest",
        name="test",
        network=None,
    )
    pod = rt._build_pod_dict(config)
    assert pod["spec"]["containers"][0]["command"] == [
        "sh",
        "-c",
        "echo 'carapace sandbox ready' && exec sleep infinity",
    ]


def test_build_pod_dict_security_context():
    rt = _make_runtime()
    config = ContainerConfig(image="sandbox:latest", name="test", network=None)
    pod = rt._build_pod_dict(config)
    sc = pod["spec"]["containers"][0]["securityContext"]
    assert sc["allowPrivilegeEscalation"] is False
    assert sc["capabilities"]["drop"] == ["ALL"]


# --- _build_statefulset_dict ---


def test_build_statefulset_dict():
    rt = _make_runtime()
    config = SandboxConfig(
        name="carapace-sandbox-abc",
        session_id="abc",
        image="sandbox:latest",
        labels={"carapace.session": "abc", "carapace.managed": "true"},
        environment={"HTTP_PROXY": "http://proxy"},
    )
    sts = rt._build_statefulset_dict(config)

    assert sts["kind"] == "StatefulSet"
    assert sts["metadata"]["name"] == "carapace-sandbox-abc"

    # Retention policy
    policy = sts["spec"]["persistentVolumeClaimRetentionPolicy"]
    assert policy["whenDeleted"] == "Delete"
    assert policy["whenScaled"] == "Retain"

    # volumeClaimTemplate
    templates = sts["spec"]["volumeClaimTemplates"]
    assert len(templates) == 1
    assert templates[0]["metadata"]["name"] == "session-data"
    assert templates[0]["spec"]["accessModes"] == ["ReadWriteOnce"]

    # Container mounts /workspace
    container = sts["spec"]["template"]["spec"]["containers"][0]
    assert any(vm["mountPath"] == "/workspace" for vm in container["volumeMounts"])


# --- create ---


@pytest.mark.asyncio
async def test_create_calls_api():
    rt = _make_runtime()

    mock_pod_instance = AsyncMock()

    async def _fake_pod(*args, **kwargs):
        return mock_pod_instance

    rt._ensure_api = AsyncMock()
    rt._get_sandbox_owner = AsyncMock(return_value=None)
    rt._delete_pod_if_exists = AsyncMock()
    rt._wait_for_running = AsyncMock()

    with patch("carapace.sandbox.kubernetes.Pod", side_effect=_fake_pod):
        config = ContainerConfig(
            image="sandbox:latest",
            name="carapace-sandbox-abc",
            network="carapace-sandbox",
            command=["sleep", "infinity"],
        )
        container_id = await rt.create(config)

    assert container_id == "carapace-sandbox-abc"
    mock_pod_instance.create.assert_called_once()
    rt._wait_for_running.assert_called_once()


# --- is_running ---


@pytest.mark.asyncio
async def test_is_running_true():
    rt = _make_runtime()
    rt._ensure_api = AsyncMock()

    mock_pod = MagicMock()
    mock_pod.status.phase = "Running"

    with patch("carapace.sandbox.kubernetes.Pod") as mock_pod_cls:
        mock_pod_cls.get = AsyncMock(return_value=mock_pod)
        assert await rt.is_running("test-pod") is True


@pytest.mark.asyncio
async def test_is_running_false():
    rt = _make_runtime()
    rt._ensure_api = AsyncMock()

    mock_pod = MagicMock()
    mock_pod.status.phase = "Pending"

    with patch("carapace.sandbox.kubernetes.Pod") as mock_pod_cls:
        mock_pod_cls.get = AsyncMock(return_value=mock_pod)
        assert await rt.is_running("test-pod") is False


# --- get_ip ---


@pytest.mark.asyncio
async def test_get_ip():
    rt = _make_runtime()
    rt._ensure_api = AsyncMock()

    mock_pod = MagicMock()
    mock_pod.status.get.return_value = "10.42.0.5"

    with patch("carapace.sandbox.kubernetes.Pod") as mock_pod_cls:
        mock_pod_cls.get = AsyncMock(return_value=mock_pod)
        ip = await rt.get_ip("test-pod", "any-network")
    assert ip == "10.42.0.5"


# --- measure_workspace_usage ---


@pytest.mark.asyncio
async def test_measure_workspace_usage_uses_df_used_bytes():
    rt = _make_runtime()
    rt.is_running = AsyncMock(return_value=True)
    rt.exec = AsyncMock(return_value=ExecResult(exit_code=0, output="1048576\n"))

    used_bytes = await rt.measure_workspace_usage("sess-1", "test-pod")

    assert used_bytes == 1_048_576
    rt.exec.assert_awaited_once_with(
        "test-pod",
        "df -B1 --output=used /workspace 2>/dev/null | tail -n 1",
        timeout=30,
    )


@pytest.mark.asyncio
async def test_measure_workspace_usage_returns_none_when_not_running():
    rt = _make_runtime()
    rt.is_running = AsyncMock(return_value=False)
    rt.exec = AsyncMock()

    used_bytes = await rt.measure_workspace_usage("sess-1", "test-pod")

    assert used_bytes is None
    rt.exec.assert_not_awaited()


# --- remove ---


@pytest.mark.asyncio
async def test_remove():
    rt = _make_runtime()
    rt._delete_pod_if_exists = AsyncMock()
    await rt.remove("test-pod")
    rt._delete_pod_if_exists.assert_called_once_with("test-pod")


# --- resolve_self_network_name ---


@pytest.mark.asyncio
async def test_resolve_self_network_name_noop():
    rt = _make_runtime()
    assert await rt.resolve_self_network_name("carapace-sandbox") == "carapace-sandbox"


# --- image_exists ---


def test_image_exists_always_true():
    rt = _make_runtime()
    assert rt.image_exists("any:tag") is True


# --- get_host_ip ---


@pytest.mark.asyncio
async def test_get_host_ip_from_env(monkeypatch):
    rt = _make_runtime()
    monkeypatch.setenv("CARAPACE_SERVICE_HOST", "10.43.0.100")
    ip = await rt.get_host_ip("any-network")
    assert ip == "10.43.0.100"


# --- StatefulSet lifecycle ---


@pytest.mark.asyncio
async def test_create_sandbox_calls_api():
    rt = _make_runtime()
    rt._ensure_api = AsyncMock()
    rt._get_sandbox_owner = AsyncMock(return_value=None)
    rt._delete_sts_if_exists = AsyncMock()
    rt._wait_for_running = AsyncMock()

    mock_sts_instance = AsyncMock()

    async def _fake_sts(*args, **kwargs):
        return mock_sts_instance

    with patch("carapace.sandbox.kubernetes.StatefulSet", side_effect=_fake_sts):
        config = SandboxConfig(
            name="carapace-sandbox-abc",
            session_id="abc",
            image="sandbox:latest",
            labels={"carapace.session": "abc"},
        )
        pod_name = await rt.create_sandbox(config)

    assert pod_name == "carapace-sandbox-abc-0"
    mock_sts_instance.create.assert_called_once()


@pytest.mark.asyncio
async def test_resume_sandbox():
    rt = _make_runtime()
    rt._ensure_api = AsyncMock()
    rt._wait_for_running = AsyncMock()

    mock_sts = AsyncMock()

    with patch("carapace.sandbox.kubernetes.StatefulSet") as mock_sts_cls:
        mock_sts_cls.get = AsyncMock(return_value=mock_sts)
        await rt.resume_sandbox("carapace-sandbox-abc")

    mock_sts.scale.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_destroy_sandbox():
    rt = _make_runtime()
    rt._delete_sts_if_exists = AsyncMock()
    rt._delete_session_pvc_if_exists = AsyncMock()
    await rt.destroy_sandbox("abc", "carapace-sandbox-abc", "carapace-sandbox-abc-0")
    rt._delete_sts_if_exists.assert_called_once_with("carapace-sandbox-abc")
    rt._delete_session_pvc_if_exists.assert_called_once_with("carapace-sandbox-abc")


@pytest.mark.asyncio
async def test_destroy_sandbox_not_found():
    rt = _make_runtime()
    rt._delete_sts_if_exists = AsyncMock()
    rt._delete_session_pvc_if_exists = AsyncMock()
    # Should not raise
    await rt.destroy_sandbox("abc", "carapace-sandbox-abc", "carapace-sandbox-abc-0")


@pytest.mark.asyncio
async def test_delete_session_pvc_if_exists() -> None:
    rt = _make_runtime()
    rt._ensure_api = AsyncMock()

    mock_pvc = AsyncMock()

    async def _fake_pvc(*args, **kwargs):
        return mock_pvc

    with patch("carapace.sandbox.kubernetes._PersistentVolumeClaim", side_effect=_fake_pvc):
        await rt._delete_session_pvc_if_exists("carapace-sandbox-abc")

    mock_pvc.delete.assert_called_once_with(force=True)


@pytest.mark.asyncio
async def test_delete_session_pvc_if_exists_ignores_not_found() -> None:
    rt = _make_runtime()
    rt._ensure_api = AsyncMock()

    mock_pvc = AsyncMock()
    mock_pvc.delete.side_effect = kr8s.NotFoundError("gone")

    async def _fake_pvc(*args, **kwargs):
        return mock_pvc

    with patch("carapace.sandbox.kubernetes._PersistentVolumeClaim", side_effect=_fake_pvc):
        await rt._delete_session_pvc_if_exists("carapace-sandbox-abc")

    mock_pvc.delete.assert_called_once_with(force=True)


# --- owner resolution ---


@pytest.mark.asyncio
async def test_get_sandbox_owner_prefers_sandboxes():
    rt = _make_runtime()
    rt._want_owner_ref = True
    rt._ensure_api = AsyncMock(return_value=object())

    collection = MagicMock()
    collection.raw = {
        "apiVersion": "carapace.dev/v1alpha1",
        "metadata": {"uid": "collection-uid"},
    }

    with patch("carapace.sandbox.kubernetes._Sandboxes") as sandboxes_cls:
        sandboxes_cls.get = AsyncMock(return_value=collection)
        with patch("carapace.sandbox.kubernetes.Deployment") as deploy_cls:
            deploy_cls.get = AsyncMock()
            owner = await rt._get_sandbox_owner()

    assert owner is not None
    assert owner.kind == "Sandboxes"
    assert owner.name == "carapace-sandboxes"
    deploy_cls.get.assert_not_called()


@pytest.mark.asyncio
async def test_get_sandbox_owner_falls_back_to_deployment():
    rt = _make_runtime()
    rt._want_owner_ref = True
    rt._ensure_api = AsyncMock(return_value=object())
    deploy_owner = MagicMock()
    deploy_owner.kind = "Deployment"
    deploy_owner.name = "carapace"
    rt._try_sandboxes_owner = AsyncMock(return_value=None)
    rt._try_server_deployment_owner = AsyncMock(return_value=deploy_owner)
    owner = await rt._get_sandbox_owner()

    assert owner is not None
    assert owner.kind == "Deployment"
    assert owner.name == "carapace"
