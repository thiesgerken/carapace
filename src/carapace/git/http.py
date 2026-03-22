from __future__ import annotations

import asyncio
import base64
import contextlib
import os
from collections.abc import Callable
from pathlib import Path

from loguru import logger

_push_lock = asyncio.Lock()


class GitHttpHandler:
    """Handles Git HTTP requests via ``git http-backend`` CGI.

    Exposed as FastAPI routes on the API server.  Authentication uses
    standard HTTP Basic Auth (``session_id:token``).
    """

    def __init__(
        self,
        *,
        knowledge_dir: Path,
        default_branch: str,
        api_port: int = 8320,
        verify_session_token: Callable[[str, str], bool] | None = None,
        on_push_success: Callable[[], None] | None = None,
    ) -> None:
        self._knowledge_dir = knowledge_dir
        self._default_branch = default_branch
        self._api_port = api_port
        self._verify_session_token = verify_session_token
        self._on_push_success = on_push_success

    def authenticate(self, authorization: str | None) -> str | None:
        """Validate an ``Authorization: Basic ...`` header.

        Returns the ``session_id`` on success, ``None`` on failure.
        """
        if not authorization:
            logger.warning("Git auth failed: no Authorization header")
            return None
        if not self._verify_session_token:
            logger.warning("Git auth failed: no verify_session_token callback")
            return None
        creds = self._extract_basic_credentials(authorization)
        if not creds:
            logger.warning("Git auth failed: malformed Basic credentials")
            return None
        session_id, token = creds
        if self._verify_session_token(session_id, token):
            return session_id
        logger.warning(f"Git auth failed: invalid token for session {session_id}")
        return None

    async def handle(
        self,
        session_id: str,
        method: str,
        path: str,
        query_string: str,
        content_type: str | None,
        body: bytes,
    ) -> tuple[int, dict[str, str], bytes]:
        """Handle a Git HTTP request and return ``(status_code, headers, body)``."""

        # Strip /git/ prefix to get the PATH_INFO for git-http-backend
        # e.g. /git/knowledge/info/refs -> /knowledge/info/refs
        path_info = path
        if path_info.startswith("/git"):
            path_info = path_info[4:]  # remove /git, keep leading /

        # Validate PATH_INFO using Path() to catch traversal segments and
        # normalise double slashes before checking the allowed repo prefix.
        path_obj = Path(path_info)
        repo_name = self._knowledge_dir.name
        allowed_prefixes = (f"/{repo_name}/", f"/{repo_name}.git/")
        if (
            ".." in path_obj.parts
            or "\\" in path_info
            or not any(str(path_obj).startswith(p) for p in allowed_prefixes)
        ):
            logger.warning(f"Rejected git request with unexpected PATH_INFO: {path_info}")
            return 403, {}, b""

        is_push = "receive-pack" in path

        # Build CGI environment
        cgi_env = {
            "GIT_PROJECT_ROOT": str(self._knowledge_dir.parent),
            "GIT_HTTP_EXPORT_ALL": "1",
            "PATH_INFO": path_info,
            "REMOTE_USER": session_id,
            "REQUEST_METHOD": method,
            "QUERY_STRING": query_string,
            "CONTENT_TYPE": content_type or "",
            "CONTENT_LENGTH": str(len(body)) if body else "",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "CARAPACE_SESSION_ID": session_id,
            "CARAPACE_DEFAULT_BRANCH": self._default_branch,
            "CARAPACE_API_PORT": str(self._api_port),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        }

        lock: contextlib.AbstractAsyncContextManager[object] = _push_lock if is_push else contextlib.nullcontext()
        async with lock:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    "http-backend",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=cgi_env,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=body),
                    timeout=120,
                )
            except TimeoutError:
                logger.error(f"git http-backend timed out for session {session_id}")
                return 504, {}, b""
            except FileNotFoundError:
                logger.error("git http-backend not found — is git installed?")
                return 500, {}, b""

        if stderr:
            logger.debug(f"git http-backend stderr: {stderr.decode(errors='replace')}")

        # Parse CGI output into status, headers, body
        status_code, headers, response_body = self._parse_cgi_output(stdout)

        # Post-push success handling
        if is_push and proc.returncode == 0 and self._on_push_success:
            try:
                self._on_push_success()
            except Exception as exc:
                logger.warning(f"Post-push callback failed: {exc}")

        return status_code, headers, response_body

    def _parse_cgi_output(self, cgi_output: bytes) -> tuple[int, dict[str, str], bytes]:
        """Parse CGI output into ``(status_code, headers_dict, body)``."""
        header_end = cgi_output.find(b"\r\n\r\n")
        if header_end == -1:
            header_end = cgi_output.find(b"\n\n")
            if header_end == -1:
                return 500, {}, b""
            sep_len = 2
        else:
            sep_len = 4

        header_block = cgi_output[:header_end]
        body = cgi_output[header_end + sep_len :]

        status_code = 200
        headers: dict[str, str] = {}
        for line in header_block.split(b"\r\n" if b"\r\n" in header_block else b"\n"):
            if line.lower().startswith(b"status:"):
                status_str = line.split(b":", 1)[1].strip().decode()
                # "200 OK" → 200
                status_code = int(status_str.split()[0])
            else:
                if b":" in line:
                    name, _, value = line.partition(b":")
                    headers[name.decode().strip()] = value.decode().strip()

        return status_code, headers, body

    @staticmethod
    def _extract_basic_credentials(header_value: str) -> tuple[str, str] | None:
        """Extract ``(session_id, token)`` from ``Basic base64(session_id:token)``."""
        try:
            scheme, _, encoded = header_value.strip().partition(" ")
            if scheme.lower() != "basic":
                return None
            decoded = base64.b64decode(encoded).decode()
            username, _, password = decoded.partition(":")
            if not username or not password:
                return None
            return username, password
        except Exception:
            return None
