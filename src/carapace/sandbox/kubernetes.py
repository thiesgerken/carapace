from __future__ import annotations

import asyncio
import os
from pathlib import Path

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client import ApiException
from kubernetes.stream import stream as k8s_stream
from loguru import logger

from carapace.sandbox.runtime import ContainerConfig, ContainerGoneError, ContainerRuntime, ExecResult, Mount


def _sanitize_pod_name(name: str) -> str:
    """Ensure a name is a valid Kubernetes pod name (lowercase alphanumeric + hyphens, max 63 chars)."""
    sanitized = name.lower().replace("_", "-")
    # Strip any characters that aren't alphanumeric or hyphens
    sanitized = "".join(c for c in sanitized if c.isalnum() or c == "-")
    return sanitized[:63].strip("-")


class KubernetesRuntime(ContainerRuntime):
    """ContainerRuntime backed by Kubernetes pods."""

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
    ) -> None:
        if os.environ.get("KUBERNETES_SERVICE_HOST"):
            k8s_config.load_incluster_config()
        else:
            k8s_config.load_kube_config()

        self._core = k8s_client.CoreV1Api()
        self._apps = k8s_client.AppsV1Api()
        self._namespace = namespace
        self._pvc_claim = pvc_claim
        self._data_dir = data_dir
        self._service_account = service_account
        self._priority_class = priority_class
        self._app_instance = app_instance

        # Optionally look up the owner Deployment UID for ownerReferences on sandbox pods
        self._owner_ref: k8s_client.V1OwnerReference | None = None
        if owner_ref:
            try:
                deployment = self._apps.read_namespaced_deployment("carapace", namespace)
                self._owner_ref = k8s_client.V1OwnerReference(
                    api_version="apps/v1",
                    kind="Deployment",
                    name="carapace",
                    uid=deployment.metadata.uid,
                    controller=False,
                    block_owner_deletion=False,
                )
                logger.info(f"KubernetesRuntime: owner Deployment UID = {deployment.metadata.uid}")
            except ApiException as exc:
                logger.warning(f"Could not look up owner Deployment: {exc.reason} — sandbox pods will lack ownerRef")

        logger.info(f"KubernetesRuntime initialized (namespace={namespace}, pvc={pvc_claim}, data_dir={data_dir})")

    def _mount_to_subpath(self, mount: Mount) -> str:
        """Convert a Mount.source (absolute host/container path) to a PVC subPath.

        The SandboxManager builds mounts with source paths like
        ``/data/memory`` or ``/data/sessions/abc/workspace/skills``.
        We strip the data_dir prefix to get the PVC-relative subPath.
        """
        source = Path(mount.source)
        try:
            return str(source.relative_to(self._data_dir))
        except ValueError:
            # Not under data_dir — use the path as-is (shouldn't happen in practice)
            logger.warning(f"Mount source {mount.source} is not under {self._data_dir}")
            return mount.source

    def _build_pod_spec(self, config: ContainerConfig) -> k8s_client.V1Pod:
        """Build a V1Pod from a ContainerConfig."""
        pod_name = _sanitize_pod_name(config.name)

        # All mounts reference the single shared PVC via subPath
        volume_mounts = [
            k8s_client.V1VolumeMount(
                name="data",
                mount_path=m.target,
                sub_path=self._mount_to_subpath(m),
                read_only=m.read_only,
            )
            for m in config.mounts
        ]

        env_vars = [k8s_client.V1EnvVar(name=k, value=v) for k, v in config.environment.items()]

        command = config.command
        if isinstance(command, str):
            command = ["bash", "-c", command]
        elif command is None:
            command = ["sh", "-c", "echo 'carapace sandbox ready' && exec sleep infinity"]

        container = k8s_client.V1Container(
            name="sandbox",
            image=config.image,
            command=command,
            env=env_vars or None,
            volume_mounts=volume_mounts or None,
            security_context=k8s_client.V1SecurityContext(
                run_as_non_root=True,
                run_as_user=1000,
                allow_privilege_escalation=False,
                capabilities=k8s_client.V1Capabilities(drop=["ALL"]),
            ),
        )

        # Standard labels for NetworkPolicy and ArgoCD
        labels = {
            "app.kubernetes.io/instance": self._app_instance,
            "app.kubernetes.io/part-of": "carapace",
            "app.kubernetes.io/component": "sandbox",
            "app.kubernetes.io/managed-by": "carapace-server",
            "app": "carapace-sandbox",
        }
        labels.update(config.labels)

        # ArgoCD tracking annotation so sandbox pods appear in the app resource tree
        annotations = {
            "argocd.argoproj.io/tracking-id": f"{self._app_instance}:/Pod:{self._namespace}/{pod_name}",
        }

        metadata = k8s_client.V1ObjectMeta(
            name=pod_name,
            namespace=self._namespace,
            labels=labels,
            annotations=annotations,
            owner_references=[self._owner_ref] if self._owner_ref else None,
        )

        pod = k8s_client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=metadata,
            spec=k8s_client.V1PodSpec(
                containers=[container],
                volumes=[
                    k8s_client.V1Volume(
                        name="data",
                        persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                            claim_name=self._pvc_claim,
                        ),
                    ),
                ],
                restart_policy="Always",
                service_account_name=self._service_account,
                automount_service_account_token=False,
                priority_class_name=self._priority_class,
            ),
        )
        return pod

    async def create(self, config: ContainerConfig) -> str:
        pod_name = _sanitize_pod_name(config.name)

        # Remove stale pod with the same name if it exists
        await self._delete_pod_if_exists(pod_name)

        pod = self._build_pod_spec(config)

        def _create() -> str:
            self._core.create_namespaced_pod(namespace=self._namespace, body=pod)
            return pod_name

        container_id = await asyncio.to_thread(_create)
        logger.info(f"Created pod {pod_name} (image={config.image})")

        # Wait for the pod to be Running
        await self._wait_for_running(pod_name, timeout=120)
        return container_id

    async def _wait_for_running(self, pod_name: str, timeout: int = 120) -> None:
        """Poll until the pod reaches Running phase."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:

            def _check() -> str:
                pod = self._core.read_namespaced_pod(name=pod_name, namespace=self._namespace)
                return pod.status.phase or "Unknown"

            phase = await asyncio.to_thread(_check)
            if phase == "Running":
                return
            if phase in ("Failed", "Succeeded"):
                raise RuntimeError(f"Pod {pod_name} entered terminal phase: {phase}")
            if asyncio.get_event_loop().time() > deadline:
                raise TimeoutError(f"Pod {pod_name} did not reach Running within {timeout}s (phase={phase})")
            await asyncio.sleep(1)

    async def exec(
        self,
        container_id: str,
        command: str | list[str],
        timeout: int = 30,
        env: dict[str, str] | None = None,
        workdir: str | None = None,
    ) -> ExecResult:
        shell_cmd = command if isinstance(command, str) else " ".join(command)

        # Kubernetes exec doesn't support workdir or env natively,
        # so we prepend cd and env vars to the shell command.
        if env:
            env_prefix = " ".join(f"{k}={v}" for k, v in env.items())
            shell_cmd = f"env {env_prefix} {shell_cmd}"
        if workdir:
            shell_cmd = f"cd {workdir} && {shell_cmd}"

        exec_command = ["bash", "-c", shell_cmd]

        def _exec() -> ExecResult:
            try:
                resp = k8s_stream(
                    self._core.connect_get_namespaced_pod_exec,
                    name=container_id,
                    namespace=self._namespace,
                    command=exec_command,
                    container="sandbox",
                    stderr=True,
                    stdin=False,
                    stdout=True,
                    tty=False,
                    _preload_content=False,
                )
                resp.run_forever(timeout=timeout)
                stdout = resp.read_stdout() or ""
                stderr = resp.read_stderr() or ""
                exit_code = resp.returncode if hasattr(resp, "returncode") and resp.returncode is not None else 0

                # Check the channel for the exit code (kubernetes websocket protocol)
                if hasattr(resp, "returncode") and resp.returncode is not None:
                    exit_code = resp.returncode
                else:
                    # Try to get exit code from the error channel
                    import json

                    err_data = resp.read_channel(3)  # ERROR channel
                    if err_data:
                        try:
                            status_obj = json.loads(err_data)
                            if status_obj.get("status") == "Success":
                                exit_code = 0
                            else:
                                causes = status_obj.get("details", {}).get("causes", [{}])
                                exit_code = int(causes[0].get("message", "1"))
                        except (json.JSONDecodeError, IndexError, ValueError, KeyError):
                            exit_code = 1 if stderr else 0

                output = stdout
                if stderr:
                    output += f"\n[stderr] {stderr}"
                return ExecResult(exit_code=exit_code, output=output)

            except ApiException as exc:
                if exc.status == 404:
                    raise ContainerGoneError(f"Pod {container_id} no longer exists") from exc
                raise

        logger.debug(f"Exec in pod {container_id}: {shell_cmd} (timeout={timeout}s)")

        try:
            coro = asyncio.to_thread(_exec)
            result = await (asyncio.wait_for(coro, timeout=timeout) if timeout else coro)
        except ContainerGoneError:
            raise
        except TimeoutError:
            logger.warning(f"Command timed out in pod {container_id} after {timeout}s: {shell_cmd}")
            return ExecResult(exit_code=-1, output=f"Error: command timed out ({timeout}s)")

        if result.exit_code != 0:
            logger.debug(f"Command exited {result.exit_code} in pod {container_id}: {shell_cmd}")
        return result

    async def remove(self, container_id: str) -> None:
        await self._delete_pod_if_exists(container_id)

    async def _delete_pod_if_exists(self, pod_name: str) -> None:
        def _delete() -> None:
            try:
                self._core.delete_namespaced_pod(
                    name=pod_name,
                    namespace=self._namespace,
                    grace_period_seconds=0,
                )
                logger.info(f"Deleted pod {pod_name}")
            except ApiException as exc:
                if exc.status == 404:
                    logger.debug(f"Pod {pod_name} already gone, skip delete")
                else:
                    raise

        await asyncio.to_thread(_delete)

    async def is_running(self, container_id: str) -> bool:
        def _check() -> bool:
            try:
                pod = self._core.read_namespaced_pod(name=container_id, namespace=self._namespace)
                return pod.status.phase == "Running"
            except ApiException:
                return False

        return await asyncio.to_thread(_check)

    async def logs(self, container_id: str, tail: int = 40) -> str:
        def _logs() -> str:
            try:
                return self._core.read_namespaced_pod_log(
                    name=container_id,
                    namespace=self._namespace,
                    tail_lines=tail,
                    timestamps=True,
                )
            except ApiException:
                return "(pod not found or logs unavailable)"

        return await asyncio.to_thread(_logs)

    def image_exists(self, tag: str) -> bool:
        """In Kubernetes, image pulls are handled by the kubelet.

        We can't check locally — always return True and let pod creation
        fail with ImagePullBackOff if the image doesn't exist.
        """
        return True

    async def get_ip(self, container_id: str, network: str) -> str | None:
        def _get_ip() -> str | None:
            try:
                pod = self._core.read_namespaced_pod(name=container_id, namespace=self._namespace)
                return pod.status.pod_ip
            except ApiException:
                return None

        return await asyncio.to_thread(_get_ip)

    async def resolve_self_network_name(self, logical_name: str) -> str:
        """No-op in Kubernetes — network names don't need resolution."""
        return logical_name

    async def ensure_network(self, name: str, *, internal: bool = False) -> None:
        """No-op in Kubernetes — networking is handled by NetworkPolicy manifests."""

    async def get_self_network_info(self) -> dict[str, str]:
        """Return the pod's own IP address."""
        import socket

        hostname = os.environ.get("HOSTNAME", socket.gethostname())
        try:
            pod = await asyncio.to_thread(self._core.read_namespaced_pod, name=hostname, namespace=self._namespace)
            ip = pod.status.pod_ip
            if ip:
                return {"pod": ip}
        except ApiException:
            pass

        # Fallback
        try:
            return {"hostname": socket.gethostbyname(hostname)}
        except Exception:
            return {}

    async def get_host_ip(self, network: str) -> str | None:
        """Return the Carapace service ClusterIP.

        In K8s, sandbox pods reach the proxy via the Service ClusterIP.
        We check CARAPACE_SERVICE_HOST (injected by K8s for services in
        the same namespace), then fall back to DNS.
        """
        service_host = os.environ.get("CARAPACE_SERVICE_HOST")
        if service_host:
            return service_host

        # Fallback: DNS resolution of the service
        import socket

        svc_dns = f"carapace.{self._namespace}.svc.cluster.local"
        try:
            return socket.gethostbyname(svc_dns)
        except socket.gaierror:
            logger.warning(f"Could not resolve {svc_dns}")
            return None
