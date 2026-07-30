"""
SSRF guard for outbound requests to user-supplied URLs (API tool
registration's "Test Connection", and actually calling a registered
tool). Registering and calling API tools is exposed to end users, so
without this check anyone could point the server at internal-only
services - cloud metadata endpoints, internal admin panels, localhost
services - and read the response back through the tool's output.
"""
import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}


def is_safe_url(url: str) -> tuple[bool, str]:
    """Returns (True, "") if the URL resolves only to public IP addresses
    and uses http/https, else (False, reason)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "Could not parse URL."

    if parsed.scheme not in ("http", "https"):
        return False, "Only http and https URLs are allowed."

    host = parsed.hostname
    if not host:
        return False, "URL has no host."

    if host.lower() in _BLOCKED_HOSTS:
        return False, "This host is not reachable."

    try:
        # Resolve every A/AAAA record - block if ANY of them is private,
        # so a host can't pass with a public record and then actually
        # connect via a private one (DNS rebinding / multi-answer tricks).
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, "Could not resolve this host."

    for info in addr_infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, "Could not resolve this host."

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, "This host resolves to a private or internal address, which isn't allowed."

    return True, ""
