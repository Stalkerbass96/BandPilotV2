"""Validation for user-configurable OpenAI-compatible provider URLs."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeProviderUrl(ValueError):
    """Raised when a provider URL can reach a non-public network target."""


def _require_public_ip(value: str) -> None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return
    if not address.is_global:
        raise UnsafeProviderUrl("Provider URL must resolve to a public IP address")


def validate_provider_base_url(url: str, *, resolve_dns: bool = False) -> str:
    """Validate and normalize an HTTP(S) provider base URL.

    Literal private/loopback/link-local addresses are always rejected. DNS is
    resolved immediately before outbound requests to prevent saved hostnames
    from resolving to internal services later.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeProviderUrl("Provider URL must use http or https")
    if not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeProviderUrl("Provider URL must contain a hostname and no credentials")
    if parsed.hostname.lower() == "localhost":
        raise UnsafeProviderUrl("Local provider URLs are not allowed")
    _require_public_ip(parsed.hostname)

    if resolve_dns:
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)
            }
        except OSError as exc:
            raise UnsafeProviderUrl("Provider hostname could not be resolved") from exc
        if not addresses:
            raise UnsafeProviderUrl("Provider hostname did not resolve")
        for address in addresses:
            _require_public_ip(address)

    return url.rstrip("/")


__all__ = ["UnsafeProviderUrl", "validate_provider_base_url"]
