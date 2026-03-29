from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path

import kr8s
from kr8s._api import Api
from kr8s.asyncio.objects import Deployment, Pod, StatefulSet
from loguru import logger

from carapace.sandbox.runtime import (
    ContainerConfig,
    ContainerGoneError,
    ContainerRuntime,
    ExecResult,
    Mount,
    SandboxConfig,
)


def _sanitize_pod_name(name: str) -> str:
    """Ensure a name is a valid Kubernetes pod name (lowercase alphanumeric + hyphens, max 63 chars)."""
    sanitized = name.lower().replace("_", "-")
    # Strip any characters that aren't alphanumeric or hyphens
    sanitized = "".join(c for c in sanitized if c.isalnum() or c == "-")
    return sanitized[:63].strip("-")


def _default_command(command: str | list[str] | None) -> list[str]:
    if isinstance(command, str):
        return ["bash", "-c", command]
    if command is None:
        return ["sh", "-c", "echo 'carapace sandbox ready' && exec sleep infinity"]
    return command


def _standard_labels(app_instance: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/instance": app_instance,
        "app.kubernetes.io/part-of": "carapace",
        "app.kubernetes.io/component": "sandbox",
        "app.kubernetes.io/managed-by": "carapace-server",
        "app": "carapace-sandbox",
    }


class KubernetesRuntime(ContainerRuntime):
    """ContainerRuntime backed by Kubernetes pods (using kr8s)."""

    def __init__(
        self,
        *,
        namespace: str = "carapace",
        pvc_claim: str = "carapace-data",
        data_dir: Path = Path("/data"),
        service_account: str | None = None,
        priority_class: str | None = None,
        owner_ref: bool = True,
        app_instance: str = "carapace",
        session_pvc_size: str = "1Gi",
        session_pvc_storage_class: str = "",
    ) -> None:
        self._namespace = namespace
        self._pvc_claim = pvc_claim
        self._data_dir = data_dir
        self._service_account = service_account
        self._priority_class = priority_class
        self._app_instance = app_instance
        self._session_pvc_size = session_pvc_size
        self._session_pvc_storage_class = session_pvc_storage_class or None
        self._want_owner_ref = owner_ref
        self._owner_deployment: Deployment | None = None

        logger.info(f"KubernetesRuntime initialized (namespace={namespace}, pvc={pvc_claim}, data_dir={data_dir})")

    async def _ensure_api(self) -> Api:
        """Lazily create the kr8s API client (must be called from async context)."""
        return await kr8s.asyncio.api(namespace=self._namespace)

    async def _get_owner_deployment(self) -> Deployment | None:
        """Look up the owner Deployment once and cache it."""
        if self._owner_deployment is not None:
            return self._owner_deployment
        if not self._want_owner_ref:
            return None
        try:
            api = await self._ensure_api()
            deploy = await Deployment.get("carapace", namespace=self._namespace, api=api)
            self._owner_deployment = deploy
            logger.info(f"KubernetesRuntime: owner Deployment UID = {deploy.raw.metadata.uid}")
            return deploy
        except (kr8s.NotFoundError, kr8s.ServerError):
            logger.warning("Could not look up owner Deployment — sandbox resources will lack ownerRef")
            self._want_owner_ref = False
            return None

    def _owner_ref_dict(self, deploy: Deployment) -> dict:
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "name": "carapace",
            "uid": deploy.raw.metadata.uid,
            "controller": False,
            "blockOwnerDeletion": False,
        }

    def _mount_to_subpath(self, mount: Mount) -> str:
        """Convert a Mount.source path to a PVC subPath."""
        source = Path(mount.source)
        try:
            return str(source.relative_to(self._data_dir))
        except ValueError:
            logger.warning(f"Mount source {mount.source} is not under {self._data_dir}")
            return mount.source

    # ------------------------------------------------------------------
    # Pod-based sandbox (ContainerConfig)
    # ------------------------------------------------------------------

    def _build_pod_dict(self, config: ContainerConfig) -> dict:
        """Build a raw Pod dict from a ContainerConfig."""
        pod_name = _sanitize_pod_name(config.name)

        volume_mounts = [
            {
                "name": "data",
                "mountPath": m.target,
                "subPath": self._mount_to_subpath(m),
                **({"readOnly": True} if m.read_only else {}),
            }
            for m in config.mounts
        ]

        env_vars = [{"name": k, "value": v} for k, v in config.environment.items()]

        labels = _standard_labels(self._app_instance)
        labels.update(config.labels)

        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": pod_name,
                "namespace": self._namespace,
                "labels": labels,
                "annotations": {
                    "argocd.argoproj.io/tracking-id": f"{self._app_instance}:/Pod:{self._namespace}/{pod_name}",
                },
            },
            "spec": {
                "containers": [
                    {
                        "name": "sandbox",
                        "image": config.image,
                        "command": _default_command(config.command),
                        **({"env": env_vars} if env_vars else {}),
                        **({"volumeMounts": volume_mounts} if volume_mounts else {}),
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "capabilities": {"drop": ["ALL"]},
                        },
                    }
                ],
                "volumes": [
                    {
                        "name": "data",
                        "persistentVolumeClaim": {"claimName": self._pvc_claim},
                    }
                ],
                "restartPolicy": "Always",
                **({"serviceAccountName": self._service_account} if self._service_account else {}),
                "automountServiceAccountToken": False,
                **({"priorityClassName": self._priority_class} if self._priority_class else {}),
            },
        }

    async def create(self, config: ContainerConfig) -> str:
        pod_name = _sanitize_pod_name(config.name)
        await self._delete_pod_if_exists(pod_name)

        api = await self._ensure_api()
        pod_dict = self._build_pod_dict(config)
        owner = await self._get_owner_deployment()
        if owner:
            pod_dict["metadata"]["ownerReferences"] = [self._owner_ref_dict(owner)]

        pod = await Pod(pod_dict, api=api)
        await pod.create()
        logger.info(f"Created pod {pod_name} (image={config.image})")

        await self._wait_for_running(pod_name, timeout=120)
        return pod_name

    async def _wait_for_running(self, pod_name: str, timeout: int = 120) -> None:
        """Poll until the pod reaches Running phase."""
        api = await self._ensure_api()
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            try:
                pod = await Pod.get(pod_name, namespace=self._namespace, api=api)
                phase = pod.status.phase or "Unknown"
            except kr8s.NotFoundError:
                phase = "Pending"

            if phase == "Running":
                return
            if phase in ("Failed", "Succeeded"):
                raise RuntimeError(f"Pod {pod_name} entered terminal phase: {phase}")
            if asyncio.get_event_loop().time() > deadline:
                raise TimeoutError(f"Pod {pod_name} did not reach Running within {timeout}s (phase={phase})")
            await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # StatefulSet lifecycle (internal)
    # ------------------------------------------------------------------

    def _build_statefulset_dict(self, config: SandboxConfig) -> dict:
        """Build a raw StatefulSet dict."""
        sts_name = _sanitize_pod_name(config.name)

        env_vars = [{"name": k, "value": v} for k, v in config.environment.items()]

        labels = _standard_labels(self._app_instance)
        labels.update(config.labels)

        pvc_spec: dict = {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": self._session_pvc_size}},
        }
        if self._session_pvc_storage_class:
            pvc_spec["storageClassName"] = self._session_pvc_storage_class

        return {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {
                "name": sts_name,
                "namespace": self._namespace,
                "labels": labels,
                "annotations": {
                    "argocd.argoproj.io/tracking-id": (
                        f"{self._app_instance}:apps/StatefulSet:{self._namespace}/{sts_name}"
                    ),
                },
            },
            "spec": {
                "replicas": 1,
                "serviceName": "",
                "persistentVolumeClaimRetentionPolicy": {
                    "whenDeleted": "Delete",
                    "whenScaled": "Retain",
                },
                "selector": {
                    "matchLabels": {"carapace.session": config.labels.get("carapace.session", sts_name)},
                },
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "containers": [
                            {
                                "name": "sandbox",
                                "image": config.image,
                                "command": _default_command(config.command),
                                **({"env": env_vars} if env_vars else {}),
                                "volumeMounts": [
                                    {"name": "session-data", "mountPath": "/workspace", "subPath": "workspace"}
                                ],
                                "securityContext": {
                                    "allowPrivilegeEscalation": False,
                                    "capabilities": {"drop": ["ALL"]},
                                },
                            }
                        ],
                        "restartPolicy": "Always",
                        **({"serviceAccountName": self._service_account} if self._service_account else {}),
                        "automountServiceAccountToken": False,
                        **({"priorityClassName": self._priority_class} if self._priority_class else {}),
                    },
                },
                "volumeClaimTemplates": [
                    {
                        "metadata": {"name": "session-data"},
                        "spec": pvc_spec,
                    }
                ],
            },
        }

    async def _create_statefulset(self, config: SandboxConfig) -> str:
        sts_name = _sanitize_pod_name(config.name)
        pod_name = f"{sts_name}-0"

        await self._delete_sts_if_exists(sts_name)

        api = await self._ensure_api()
        sts_dict = self._build_statefulset_dict(config)
        owner = await self._get_owner_deployment()
        if owner:
            sts_dict["metadata"]["ownerReferences"] = [self._owner_ref_dict(owner)]

        sts = await StatefulSet(sts_dict, api=api)
        await sts.create()
        logger.info(f"Created StatefulSet {sts_name} (image={config.image})")

        await self._wait_for_running(pod_name, timeout=120)
        return pod_name

    async def _scale_statefulset(self, name: str, replicas: int) -> None:
        sts_name = _sanitize_pod_name(name)
        api = await self._ensure_api()
        sts = await StatefulSet.get(sts_name, namespace=self._namespace, api=api)
        await sts.scale(replicas)
        logger.info(f"Scaled StatefulSet {sts_name} to {replicas} replicas")

        if replicas > 0:
            await self._wait_for_running(f"{sts_name}-0", timeout=120)

    # ------------------------------------------------------------------
    # Sandbox lifecycle (public protocol)
    # ------------------------------------------------------------------

    async def create_sandbox(self, config: SandboxConfig) -> str:
        """Create a StatefulSet-backed sandbox with a per-session PVC."""
        return await self._create_statefulset(config)

    async def resume_sandbox(self, name: str) -> None:
        """Scale the StatefulSet back to 1 replica (PVC is retained)."""
        await self._scale_statefulset(name, 1)

    async def suspend_sandbox(self, name: str, container_id: str) -> None:
        """Scale the StatefulSet to 0 — PVC survives for later resume."""
        try:
            await self._scale_statefulset(name, 0)
        except Exception:
            logger.opt(exception=True).warning(f"Scale-down failed for {name}, deleting pod")
            await self._delete_pod_if_exists(container_id)

    async def destroy_sandbox(self, name: str, container_id: str) -> None:
        """Delete the StatefulSet entirely (PVC cleaned up by retention policy)."""
        await self._delete_sts_if_exists(_sanitize_pod_name(name))

    async def sandbox_exists(self, name: str) -> str | None:
        """Return the pod name if the StatefulSet exists, else None."""
        sts_name = _sanitize_pod_name(name)
        api = await self._ensure_api()
        sts = await StatefulSet(
            {
                "apiVersion": "apps/v1",
                "kind": "StatefulSet",
                "metadata": {"name": sts_name, "namespace": self._namespace},
            },
            api=api,
        )
        if await sts.exists():
            return f"{sts_name}-0"
        return None

    async def _delete_sts_if_exists(self, sts_name: str) -> None:
        api = await self._ensure_api()
        sts = await StatefulSet(
            {
                "apiVersion": "apps/v1",
                "kind": "StatefulSet",
                "metadata": {"name": sts_name, "namespace": self._namespace},
            },
            api=api,
        )
        try:
            await sts.delete(propagation_policy="Foreground", force=True)
            logger.info(f"Deleted StatefulSet {sts_name}")
        except kr8s.NotFoundError:
            logger.debug(f"StatefulSet {sts_name} already gone, skip delete")

    # ------------------------------------------------------------------
    # Pod helpers
    # ------------------------------------------------------------------

    async def _delete_pod_if_exists(self, pod_name: str) -> None:
        api = await self._ensure_api()
        pod = await Pod(
            {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": pod_name, "namespace": self._namespace}},
            api=api,
        )
        try:
            await pod.delete(force=True)
            logger.info(f"Deleted pod {pod_name}")
        except kr8s.NotFoundError:
            logger.debug(f"Pod {pod_name} already gone, skip delete")

    # ------------------------------------------------------------------
    # Exec
    # ------------------------------------------------------------------

    async def exec(
        self,
        container_id: str,
        command: str | list[str],
        timeout: int = 30,
        env: dict[str, str] | None = None,
        workdir: str | None = None,
    ) -> ExecResult:
        shell_cmd = command if isinstance(command, str) else " ".join(command)

        if workdir:
            shell_cmd = f"cd {workdir} && {shell_cmd}"
        if env:
            env_prefix = " ".join(f"{k}={v}" for k, v in env.items())
            shell_cmd = f"env {env_prefix} {shell_cmd}"

        exec_command = ["bash", "-c", shell_cmd]
        logger.debug(f"Exec in pod {container_id}: {shell_cmd} (timeout={timeout}s)")

        try:
            api = await self._ensure_api()
            pod = await Pod.get(container_id, namespace=self._namespace, api=api)

            async def _do_exec() -> ExecResult:
                completed = await pod.exec(
                    exec_command,
                    container="sandbox",
                    check=False,
                    capture_output=True,
                )
                stdout = completed.stdout.decode() if completed.stdout else ""
                stderr = completed.stderr.decode() if completed.stderr else ""
                exit_code = completed.returncode

                output = stdout
                if stderr:
                    output += f"\n[stderr] {stderr}"
                return ExecResult(exit_code=exit_code, output=output)

            if timeout:
                result = await asyncio.wait_for(_do_exec(), timeout=timeout)
            else:
                result = await _do_exec()

        except kr8s.NotFoundError as exc:
            raise ContainerGoneError(f"Pod {container_id} no longer exists") from exc
        except kr8s.ExecError:
            return ExecResult(exit_code=1, output="Error: exec protocol error")
        except TimeoutError:
            logger.warning(f"Command timed out in pod {container_id} after {timeout}s: {shell_cmd}")
            return ExecResult(exit_code=-1, output=f"Error: command timed out ({timeout}s)")

        if result.exit_code != 0:
            logger.debug(f"Command exited {result.exit_code} in pod {container_id}: {shell_cmd}")
        return result

    # ------------------------------------------------------------------
    # Low-level operations
    # ------------------------------------------------------------------

    async def remove(self, container_id: str) -> None:
        await self._delete_pod_if_exists(container_id)

    async def is_running(self, container_id: str) -> bool:
        try:
            api = await self._ensure_api()
            pod = await Pod.get(container_id, namespace=self._namespace, api=api)
            return pod.status.phase == "Running"
        except (kr8s.NotFoundError, kr8s.ServerError):
            return False

    async def logs(self, container_id: str, tail: int = 40) -> str:
        try:
            api = await self._ensure_api()
            pod = await Pod.get(container_id, namespace=self._namespace, api=api)
            lines: list[str] = []
            async for line in pod.logs(tail_lines=tail, timestamps=True):
                lines.append(line)
            return "\n".join(lines)
        except (kr8s.NotFoundError, kr8s.ServerError):
            return "(pod not found or logs unavailable)"

    def image_exists(self, tag: str) -> bool:
        """In Kubernetes, image pulls are handled by the kubelet."""
        return True

    async def get_ip(self, container_id: str, network: str) -> str | None:
        try:
            api = await self._ensure_api()
            pod = await Pod.get(container_id, namespace=self._namespace, api=api)
            return pod.status.get("podIP")
        except (kr8s.NotFoundError, kr8s.ServerError):
            return None

    async def resolve_self_network_name(self, logical_name: str) -> str:
        """No-op in Kubernetes — network names don't need resolution."""
        return logical_name

    async def ensure_network(self, name: str, *, internal: bool = False) -> None:
        """No-op in Kubernetes — networking is handled by NetworkPolicy manifests."""

    async def get_self_network_info(self) -> dict[str, str]:
        """Return the pod's own IP address."""
        hostname = os.environ.get("HOSTNAME", socket.gethostname())
        try:
            api = await self._ensure_api()
            pod = await Pod.get(hostname, namespace=self._namespace, api=api)
            ip = pod.status.get("podIP")
            if ip:
                return {"pod": ip}
        except (kr8s.NotFoundError, kr8s.ServerError):
            pass

        try:
            return {"hostname": socket.gethostbyname(hostname)}
        except Exception:
            return {}

    async def get_host_ip(self, network: str) -> str | None:
        """Return the Carapace service ClusterIP."""
        service_host = os.environ.get("CARAPACE_SERVICE_HOST")
        if service_host:
            return service_host

        svc_dns = f"carapace.{self._namespace}.svc.cluster.local"
        try:
            return socket.gethostbyname(svc_dns)
        except socket.gaierror:
            logger.warning(f"Could not resolve {svc_dns}")
            return None
