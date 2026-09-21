"""Canonical client address for rate limiting; forwarded headers are untrusted.

Only an explicitly allowlisted immediate peer may supply one X-Real-IP value.
The reverse proxy must overwrite that header and block direct application access.
Never select an address from a user-controlled X-Forwarded-For chain.
"""

from ipaddress import ip_address

from django.conf import settings


def canonical_ip(value):
    if not isinstance(value, str) or not value or len(value) > 64 or "%" in value:
        return None
    try:
        address = ip_address(value)
    except ValueError:
        return None
    address = getattr(address, "ipv4_mapped", None) or address
    if address.is_unspecified or address.is_multicast:
        return None
    return str(address)


def trusted_proxy_ips():
    values = getattr(settings, "TRUSTED_PROXY_IPS", [])
    if not isinstance(values, (list, tuple)):
        return set()
    # Invalid configuration must not broaden trust. Static deployment checks
    # additionally reject it before a service is released.
    return {ip for value in values if (ip := canonical_ip(value)) is not None}


def client_address(request):
    peer = canonical_ip(request.META.get("REMOTE_ADDR", ""))
    if peer is None:
        return "unknown"
    if peer in trusted_proxy_ips():
        forwarded = canonical_ip(request.META.get("HTTP_X_REAL_IP", ""))
        if forwarded is not None:
            return forwarded
    # Missing/invalid forwarded data shares the peer's bucket rather than
    # allowing clients to choose arbitrary rate-limit keys.
    return peer
