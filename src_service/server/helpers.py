"""Request/handler helper utilities for extracting common request-derived values.

Contains small, well-tested helpers to safely retrieve the Host header, the
client address as "ip:port", and a public IP derived from proxy headers.
"""
from typing import Optional


def get_host_header(handler) -> Optional[str]:
    """Return the Host header value or None if not available.

    Safe to call with handler objects that may not have headers or that raise.
    """
    try:
        return handler.headers.get("Host") if hasattr(handler, "headers") else None
    except Exception:
        return None


def get_client_addr(handler) -> Optional[str]:
    """Return a string "ip:port" derived from handler.client_address or None.

    The function handles missing attributes or exceptions and returns None
    in those cases.
    """
    try:
        ca = handler.client_address
        return f"{ca[0]}:{ca[1]}"
    except Exception:
        return None


def get_public_ip(handler) -> Optional[str]:
    """Return the public IP inferred from X-Forwarded-For or X-Real-IP headers.

    X-Forwarded-For may contain a comma-separated list; the first entry is
    returned. If neither header is present or an error occurs, returns None.
    """
    try:
        if not hasattr(handler, "headers"):
            return None
        xff = handler.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
        xr = handler.headers.get("X-Real-IP")
        if xr:
            return xr.strip()
        return None
    except Exception:
        return None
