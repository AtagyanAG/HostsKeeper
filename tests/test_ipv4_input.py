"""IPv4 Host / IP field helpers."""

from hostskeeper.desktop.ipv4_input import (
    is_valid_ipv4,
    looks_like_ipv4,
    normalize_ipv4_commas,
)


def test_normalize_replaces_commas_only_for_ipv4_shape() -> None:
    assert normalize_ipv4_commas("192,168,1,1") == "192.168.1.1"
    assert normalize_ipv4_commas(" 10,0,0,1 ") == "10.0.0.1"
    assert normalize_ipv4_commas("host.example.com") == "host.example.com"
    assert normalize_ipv4_commas("192.168.1.1") == "192.168.1.1"
    assert normalize_ipv4_commas("192,168,1") == "192,168,1"
    assert normalize_ipv4_commas("db-server") == "db-server"


def test_looks_like_and_valid() -> None:
    assert looks_like_ipv4("192.168.1.1")
    assert is_valid_ipv4("192.168.1.1")
    assert looks_like_ipv4("192.168.1.999")
    assert not is_valid_ipv4("192.168.1.999")
    assert not looks_like_ipv4("host.example.com")
    assert not looks_like_ipv4("192,168,1,1")
