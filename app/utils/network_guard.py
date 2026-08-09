"""
SSRF guard for outbound requests to user-supplied URLs (API tool
registration's "Test Connection", and actually calling a registered
tool). Registering and calling API tools is exposed to end users, so
without this check anyone could point the server at internal-only
services - cloud metadata endpoints, internal admin panels, localhost
services - and read the response back through the tool's output.
"""
import ipaddress
import re
import socket
from urllib.parse import urlparse

_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}


def build_full_api_url(base_url: str, endpoint: str) -> str:
    """
    Joins a registered API tool's base_url + endpoint into one URL,
    correctly separating a query string that ended up typed into the
    endpoint field - e.g. "latest&currency=INR&unit=kg" (missing its
    leading "?", a common mistake when someone pastes a full query
    string into just the endpoint box) or "latest?currency=INR&unit=kg"
    (correctly formed). A naive f"{base_url}/{endpoint}" concatenation
    leaves the "&key=value" pairs stuck in the URL path with no "?"
    ahead of them, which the target API then rejects outright as an
    unrecognized path rather than "latest" with query params - this is
    exactly what happened calling api.metals.dev.

    Also strips any stray whitespace from the endpoint, since a pasted
    query string picking up a space (e.g. "INR &unit=kg") breaks the URL
    just as badly.
    """
    endpoint_clean = re.sub(r'\s+', '', endpoint or '')

    if '?' in endpoint_clean:
        ep_path, _, ep_query = endpoint_clean.partition('?')
    else:
        segments = endpoint_clean.split('&')
        ep_path = segments[0]
        ep_query = '&'.join(segments[1:])

    full_url = f"{base_url.rstrip('/')}/{ep_path.lstrip('/')}"
    if ep_query:
        full_url += '?' + ep_query
    return full_url


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
