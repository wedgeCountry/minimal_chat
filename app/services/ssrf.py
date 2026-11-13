"""SSRF-Schutz fuer user-gesteuerte LLM-URLs (Settings + Chat), siehe AGENTS.md Regel 11."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import ParseResult, urlparse

# CGNAT: ip.is_private ist hier False
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class LlmUrlValidator:
    """Validiert LLM-Base-URLs: nur http/https ohne Credentials; ohne
    ``allow_private`` werden per DNS private/reservierte Ziel-IPs abgelehnt.

    Achtung: der DNS-Lookup in ``validate`` ist blockierend und gehoert in
    async-Kontexten nach ``asyncio.to_thread``.
    """

    def __init__(self, allow_private: bool = False) -> None:
        self._allow_private = allow_private

    def validate(self, base_url: str) -> str:
        url = (base_url or "").strip()
        parsed = self._parse(url)
        if not self._allow_private:
            self._ensure_public_target(parsed)
        return url

    @staticmethod
    def _parse(url: str) -> ParseResult:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Ungueltige LLM-Base-URL (nur http/https mit Host erlaubt)")
        if parsed.username or parsed.password:
            raise ValueError("Credentials in der LLM-URL sind nicht erlaubt")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("Ungueltiger Port in der LLM-Base-URL") from exc
        return parsed

    def _ensure_public_target(self, parsed: ParseResult) -> None:
        try:
            infos = socket.getaddrinfo(parsed.hostname, parsed.port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise ValueError(f"LLM-Host nicht aufloesbar: {parsed.hostname}") from exc
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if self._is_blocked_target(ip):
                raise ValueError(
                    f"LLM-Ziel {ip} liegt in einem privaten/reservierten Netz und ist blockiert "
                    "(LEANCHAT_ALLOW_PRIVATE_LLM=1 erlaubt private Ziele)"
                )

    @staticmethod
    def _is_blocked_target(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
            or ip in _CGNAT
        )


def validate_llm_base_url(base_url: str, allow_private: bool = False) -> str:
    return LlmUrlValidator(allow_private=allow_private).validate(base_url)
