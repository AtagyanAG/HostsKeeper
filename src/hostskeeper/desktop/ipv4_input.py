"""Host / IP field helpers: comma→dot for IPv4-like input."""

from __future__ import annotations

import ipaddress
import re

# Four decimal groups separated by commas (locale typo for IPv4).
_IPV4_COMMA = re.compile(r"^\d{1,3}(,\d{1,3}){3}$")
# Four decimal groups separated by dots (may still be invalid octets).
_IPV4_DOTTED = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def normalize_ipv4_commas(value: str) -> str:
    """If value is IPv4-shaped with commas, return dots version; else unchanged."""
    stripped = value.strip()
    if _IPV4_COMMA.fullmatch(stripped):
        return stripped.replace(",", ".")
    return value


def looks_like_ipv4(value: str) -> bool:
    return bool(_IPV4_DOTTED.fullmatch(value.strip()))


def is_valid_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value.strip())
    except ValueError:
        return False
    return True
