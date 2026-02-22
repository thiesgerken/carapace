from __future__ import annotations

import asyncio
import base64
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from loguru import logger

_CONNECT_OK = b"HTTP/1.1 200 Connection Established\r\n\r\n"
_FORBIDDEN_RESPONSE = (
    b"HTTP/1.1 403 Forbidden\r\nContent-Length: 30\r\nConnection: close\r\n\r\nDomain blocked by proxy policy"
)
_BAD_REQUEST = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 11\r\nConnection: close\r\n\r\nBad Request"
_RELAY_BUF = 32 * 1024


class DomainDecision(StrEnum):
    ALLOW_ONCE = "allow_once"
    ALLOW_ALL_ONCE = "allow_all_once"
    ALLOW_15MIN = "allow_15min"
    ALLOW_ALL_15MIN = "allow_all_15min"
    DENY = "deny"


@dataclass
class DomainApprovalPending:
    """Represents one in-flight proxy domain authorization request."""

    request_id: str
    session_id: str
    domain: str
    command: str  # the exec command that triggered the connection attempt
    future: asyncio.Future[DomainDecision]


def domain_matches(domain: str, pattern: str) -> bool:
    """Check if *domain* matches *pattern*.

    Exact match: ``"example.com"`` matches only ``"example.com"``.
    Wildcard:    ``"*.example.com"`` matches ``"sub.example.com"`` and
                 ``"a.b.example.com"`` but **not** ``"example.com"`` itself.
    """
    if pattern.startswith("*."):
        suffix = pattern[1:]  # ".example.com"
        return domain.endswith(suffix) and domain != suffix.lstrip(".")
    return domain == pattern


class ProxyServer:
    """Async HTTP forward-proxy with per-session domain allowlists.

    Supports plain HTTP forwarding and HTTPS via CONNECT tunnelling.
    No MITM -- domain-level control only.
    """

    def __init__(
        self,
        get_session_by_token: Callable[[str], str | None],
        get_allowed_domains: Callable[[str], set[str]],
        request_approval: Callable[[str, str], Awaitable[bool]] | None = None,
        host: str = "0.0.0.0",
        port: int = 3128,
    ) -> None:
        self._get_session_by_token = get_session_by_token
        self._get_domains = get_allowed_domains
        self._request_approval = request_approval
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client,
            self._host,
            self._port,
        )
        logger.info(f"Proxy server listening on {self._host}:{self._port}")

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Proxy server stopped")

    # ------------------------------------------------------------------

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        client_ip = peer[0] if peer else "unknown"

        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=30)
            if not request_line:
                return

            line = request_line.decode("latin-1", errors="replace").strip()
            parts = line.split()
            if len(parts) < 3:
                writer.write(_BAD_REQUEST)
                await writer.drain()
                return

            # Read all headers so we can extract Proxy-Authorization
            raw_headers: list[bytes] = []
            proxy_token: str | None = None
            while True:
                hdr = await asyncio.wait_for(reader.readline(), timeout=10)
                if hdr in (b"\r\n", b"\n", b""):
                    break
                raw_headers.append(hdr)
                if hdr.lower().startswith(b"proxy-authorization:"):
                    proxy_token = self._extract_proxy_token(hdr)

            session_id = self._get_session_by_token(proxy_token) if proxy_token else None
            if session_id is None:
                logger.warning(f"Proxy: no valid token from {client_ip}, rejecting")
                writer.write(_FORBIDDEN_RESPONSE)
                await writer.drain()
                return

            method = parts[0].upper()
            if method == "CONNECT":
                await self._handle_connect(reader, writer, session_id, client_ip, parts[1])
            else:
                await self._handle_http(
                    reader,
                    writer,
                    session_id,
                    client_ip,
                    method,
                    parts[1],
                    parts[2],
                    raw_headers,
                )
        except TimeoutError:
            logger.debug(f"Proxy: timeout reading from {client_ip}")
        except (ConnectionError, BrokenPipeError):
            pass
        except Exception as exc:
            logger.debug(f"Proxy: error handling {client_ip}: {exc}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    def _extract_proxy_token(header_line: bytes) -> str | None:
        """Extract the username from a ``Proxy-Authorization: Basic ...`` header.

        The token is stored as the username with an empty password
        (``base64(token:)``).
        """
        try:
            _, value = header_line.split(b":", 1)
            scheme, _, encoded = value.strip().partition(b" ")
            if scheme.lower() != b"basic":
                return None
            decoded = base64.b64decode(encoded).decode()
            username, _, _ = decoded.partition(":")
            return username or None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # CONNECT (HTTPS tunnelling)
    # ------------------------------------------------------------------

    async def _handle_connect(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        session_id: str,
        client_ip: str,
        target: str,
    ) -> None:
        domain, port = self._parse_host_port(target, default_port=443)
        if not await self._authorize_domain(session_id, domain):
            logger.warning(f"Proxy CONNECT denied: {domain} (session={session_id}, ip={client_ip})")
            writer.write(_FORBIDDEN_RESPONSE)
            await writer.drain()
            return

        try:
            remote_reader, remote_writer = await asyncio.wait_for(
                asyncio.open_connection(domain, port),
                timeout=30,
            )
        except Exception as exc:
            logger.debug(f"Proxy CONNECT: cannot reach {domain}:{port} — {exc}")
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await writer.drain()
            return

        logger.info(f"Proxy CONNECT allowed: {domain}:{port} (session={session_id})")
        writer.write(_CONNECT_OK)
        await writer.drain()

        await self._relay(reader, writer, remote_reader, remote_writer)

    # ------------------------------------------------------------------
    # Plain HTTP forwarding
    # ------------------------------------------------------------------

    async def _handle_http(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        session_id: str,
        client_ip: str,
        method: str,
        url: str,
        http_version: str,
        raw_headers: list[bytes],
    ) -> None:
        domain, port, path = self._parse_absolute_url(url)
        if not domain:
            writer.write(_BAD_REQUEST)
            await writer.drain()
            return

        if not await self._authorize_domain(session_id, domain):
            logger.warning(f"Proxy HTTP denied: {method} {domain}{path} (session={session_id}, ip={client_ip})")
            writer.write(_FORBIDDEN_RESPONSE)
            await writer.drain()
            return

        # Filter out proxy-specific headers and find content-length
        headers: list[bytes] = []
        content_length = 0
        for hdr in raw_headers:
            lower = hdr.lower()
            if lower.startswith(b"proxy-"):
                continue
            if lower.startswith(b"content-length:"):
                content_length = int(hdr.split(b":", 1)[1].strip())
            headers.append(hdr)

        body = b""
        if content_length > 0:
            body = await asyncio.wait_for(reader.readexactly(content_length), timeout=30)

        try:
            remote_reader, remote_writer = await asyncio.wait_for(
                asyncio.open_connection(domain, port),
                timeout=30,
            )
        except Exception as exc:
            logger.debug(f"Proxy HTTP: cannot reach {domain}:{port} — {exc}")
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await writer.drain()
            return

        logger.info(f"Proxy HTTP allowed: {method} {domain}{path} (session={session_id})")

        # Rebuild request with relative path
        request_line = f"{method} {path} {http_version}\r\n".encode()
        remote_writer.write(request_line)
        for h in headers:
            remote_writer.write(h)
        remote_writer.write(b"\r\n")
        if body:
            remote_writer.write(body)
        await remote_writer.drain()

        # Stream response back
        try:
            while True:
                chunk = await asyncio.wait_for(remote_reader.read(_RELAY_BUF), timeout=60)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
        except (ConnectionError, TimeoutError):
            pass
        finally:
            remote_writer.close()

    # ------------------------------------------------------------------
    # Bidirectional relay for CONNECT tunnels
    # ------------------------------------------------------------------

    @staticmethod
    async def _relay(
        c_reader: asyncio.StreamReader,
        c_writer: asyncio.StreamWriter,
        r_reader: asyncio.StreamReader,
        r_writer: asyncio.StreamWriter,
    ) -> None:
        async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await src.read(_RELAY_BUF)
                    if not data:
                        break
                    dst.write(data)
                    await dst.drain()
            except (ConnectionError, BrokenPipeError, asyncio.CancelledError):
                pass

        t1 = asyncio.create_task(_pipe(c_reader, r_writer))
        t2 = asyncio.create_task(_pipe(r_reader, c_writer))
        try:
            await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            t1.cancel()
            t2.cancel()
            for t in (t1, t2):
                with contextlib.suppress(asyncio.CancelledError):
                    await t
            for w in (r_writer, c_writer):
                with contextlib.suppress(Exception):
                    w.close()

    # ------------------------------------------------------------------
    # Domain authorization (allowlist check + optional approval request)
    # ------------------------------------------------------------------

    async def _authorize_domain(self, session_id: str, domain: str) -> bool:
        """Return True if *domain* is allowed for *session_id*.

        If the domain is not in the allowlist and a ``request_approval``
        callback is configured, the connection is suspended until the user
        makes a decision (the callback is responsible for updating the
        allowlist on approval).  Without a callback, unknown domains are
        denied immediately.
        """
        if self._is_allowed(session_id, domain):
            return True
        if self._request_approval is None:
            return False
        logger.info(f"Proxy: suspending connection to {domain} (session={session_id}), requesting approval")
        return await self._request_approval(session_id, domain)

    def _is_allowed(self, session_id: str, domain: str) -> bool:
        allowed = self._get_domains(session_id)
        if "*" in allowed:
            return True
        domain = domain.lower()
        return any(domain_matches(domain, p.lower()) for p in allowed)

    # ------------------------------------------------------------------
    # URL / host parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_host_port(target: str, default_port: int = 443) -> tuple[str, int]:
        if ":" in target:
            host, port_str = target.rsplit(":", 1)
            try:
                return host, int(port_str)
            except ValueError:
                return target, default_port
        return target, default_port

    @staticmethod
    def _parse_absolute_url(url: str) -> tuple[str, int, str]:
        """Parse ``http://host:port/path`` -> ``(host, port, path)``.

        Returns ``("", 0, "")`` when the URL is not absolute.
        """
        if not url.lower().startswith("http://"):
            return "", 0, ""
        rest = url[7:]  # strip "http://"
        slash_idx = rest.find("/")
        if slash_idx == -1:
            host_part, path = rest, "/"
        else:
            host_part, path = rest[:slash_idx], rest[slash_idx:]

        if ":" in host_part:
            host, port_str = host_part.rsplit(":", 1)
            try:
                return host, int(port_str), path
            except ValueError:
                return host_part, 80, path
        return host_part, 80, path
