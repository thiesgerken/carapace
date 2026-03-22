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

    Integrated into the proxy server (port 3128). Validates session tokens
    and spawns ``git http-backend`` as a subprocess.
    """

    def __init__(
        self,
        *,
        knowledge_dir: Path,
        default_branch: str,
        get_session_by_token: Callable[[str], str | None],
        api_port: int = 8321,
        on_push_success: Callable[[], None] | None = None,
    ) -> None:
        self._knowledge_dir = knowledge_dir
        self._default_branch = default_branch
        self._get_session_by_token = get_session_by_token
        self._api_port = api_port
        self._on_push_success = on_push_success

    def _extract_basic_auth(self, raw_headers: list[bytes]) -> str | None:
        """Extract password from ``Authorization: Basic ...`` header."""
        for hdr in raw_headers:
            lower = hdr.lower()
            if lower.startswith(b"authorization:"):
                try:
                    _, value = hdr.split(b":", 1)
                    scheme, _, encoded = value.strip().partition(b" ")
                    if scheme.lower() != b"basic":
                        continue
                    decoded = base64.b64decode(encoded).decode()
                    _, _, password = decoded.partition(":")
                    return password or None
                except Exception:
                    continue
        return None

    async def handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        method: str,
        path: str,
        query_string: str,
        raw_headers: list[bytes],
        body: bytes,
    ) -> None:
        """Handle a Git HTTP request by delegating to ``git http-backend``."""
        # Authenticate via Basic Auth (password = proxy-token)
        token = self._extract_basic_auth(raw_headers)
        session_id = self._get_session_by_token(token) if token else None
        if session_id is None:
            writer.write(b'HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: Basic realm="git"\r\n\r\n')
            await writer.drain()
            return

        # Strip /git/ prefix to get the PATH_INFO for git-http-backend
        # e.g. /git/knowledge/info/refs -> /knowledge/info/refs
        path_info = path
        if path_info.startswith("/git"):
            path_info = path_info[4:]  # remove /git, keep leading /

        # Validate PATH_INFO: must address only the intended repo to prevent
        # git http-backend from serving arbitrary repos under the parent dir.
        repo_name = self._knowledge_dir.name
        allowed_prefixes = (f"/{repo_name}/", f"/{repo_name}.git/")
        if not any(path_info.startswith(p) for p in allowed_prefixes):
            logger.warning(f"Rejected git request with unexpected PATH_INFO: {path_info}")
            writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            await writer.drain()
            return

        is_push = "receive-pack" in path

        # Build CGI environment
        cgi_env = {
            "GIT_PROJECT_ROOT": str(self._knowledge_dir.parent),
            "GIT_HTTP_EXPORT_ALL": "1",
            "PATH_INFO": path_info,
            "REMOTE_USER": session_id,
            "REQUEST_METHOD": method,
            "QUERY_STRING": query_string,
            "CONTENT_TYPE": self._get_header(raw_headers, b"content-type") or "",
            "CONTENT_LENGTH": str(len(body)) if body else "",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "CARAPACE_SESSION_ID": session_id,
            "CARAPACE_DEFAULT_BRANCH": self._default_branch,
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
                writer.write(b"HTTP/1.1 504 Gateway Timeout\r\n\r\n")
                await writer.drain()
                return
            except FileNotFoundError:
                logger.error("git http-backend not found — is git installed?")
                writer.write(b"HTTP/1.1 500 Internal Server Error\r\n\r\n")
                await writer.drain()
                return

        if stderr:
            logger.debug(f"git http-backend stderr: {stderr.decode(errors='replace')}")

        # Parse CGI output: headers\r\n\r\nbody
        response = self._cgi_to_http(stdout)
        writer.write(response)
        await writer.drain()

        # Post-push success handling
        if is_push and proc.returncode == 0 and self._on_push_success:
            try:
                self._on_push_success()
            except Exception as exc:
                logger.warning(f"Post-push callback failed: {exc}")

    def _cgi_to_http(self, cgi_output: bytes) -> bytes:
        """Convert CGI output to an HTTP response."""
        # CGI output: "Status: 200 OK\r\nContent-Type: ...\r\n\r\nbody"
        # or just "Content-Type: ...\r\n\r\nbody" (default 200)
        header_end = cgi_output.find(b"\r\n\r\n")
        if header_end == -1:
            header_end = cgi_output.find(b"\n\n")
            if header_end == -1:
                return b"HTTP/1.1 500 Internal Server Error\r\n\r\n"
            sep_len = 2
        else:
            sep_len = 4

        header_block = cgi_output[:header_end]
        body = cgi_output[header_end + sep_len :]

        # Extract status line from headers
        status_line = "200 OK"
        filtered_headers: list[bytes] = []
        for line in header_block.split(b"\r\n" if b"\r\n" in header_block else b"\n"):
            if line.lower().startswith(b"status:"):
                status_line = line.split(b":", 1)[1].strip().decode()
            else:
                filtered_headers.append(line)

        response = f"HTTP/1.1 {status_line}\r\n".encode()
        for hdr in filtered_headers:
            response += hdr + b"\r\n"
        response += b"\r\n"
        response += body
        return response

    @staticmethod
    def _get_header(raw_headers: list[bytes], name: bytes) -> str | None:
        """Get a header value by name (case-insensitive)."""
        name_lower = name.lower()
        for hdr in raw_headers:
            if hdr.lower().startswith(name_lower + b":"):
                return hdr.split(b":", 1)[1].strip().decode()
        return None
