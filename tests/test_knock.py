"""TCP/UDP port-knock helper (no network required for parse/serialize)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from hostskeeper.session.knock import (
    KnockStep,
    format_knock_sequence,
    parse_knock_sequence,
    perform_knock,
)
from hostskeeper.vault import Address, Host, Vault


def test_parse_and_format_mixed_sequence() -> None:
    steps = parse_knock_sequence("4011, 5022:udp,6033:tcp")
    assert steps == [
        KnockStep(4011, "tcp"),
        KnockStep(5022, "udp"),
        KnockStep(6033, "tcp"),
    ]
    assert format_knock_sequence(steps) == "4011,5022:udp,6033"
    with pytest.raises(ValueError):
        parse_knock_sequence("0")
    with pytest.raises(ValueError):
        parse_knock_sequence("22:icmp")


def test_address_knock_steps_roundtrip(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "k.vault", "pass")
    host = vault.add_host(Host(name="h"))
    addr = vault.add_address(
        Address(
            host_id=host.id,
            host="192.0.2.9",
            knock_enabled=True,
            knock_steps=[
                {"port": 4011, "protocol": "tcp"},
                {"port": 5022, "protocol": "udp"},
            ],
            knock_delay_ms=150,
            knock_pause_ms=250,
        )
    )
    loaded = vault.get_address(addr.id)
    assert loaded.knock_enabled is True
    assert loaded.knock_steps == [
        {"port": 4011, "protocol": "tcp"},
        {"port": 5022, "protocol": "udp"},
    ]
    assert loaded.knock_ports == [4011, 5022]

    # Legacy knock_ports-only payload still loads as tcp steps.
    raw = loaded.to_dict()
    del raw["knock_steps"]
    raw["knock_ports"] = [9, 8]
    legacy = Address.from_dict(raw)
    assert legacy.knock_steps == [
        {"port": 9, "protocol": "tcp"},
        {"port": 8, "protocol": "tcp"},
    ]


def test_perform_knock_tcp_and_udp() -> None:
    seen: list[tuple[str, int]] = []

    class FakeTcp:
        def settimeout(self, _t: float) -> None:
            return None

        def connect(self, endpoint: tuple[str, int]) -> None:
            seen.append(("tcp", endpoint[1]))
            raise OSError("closed")

        def close(self) -> None:
            return None

    class FakeUdp:
        def sendto(self, _data: bytes, endpoint: tuple[str, int]) -> int:
            seen.append(("udp", endpoint[1]))
            return 0

        def close(self) -> None:
            return None

    def fake_socket(family: int, type_: int, *args, **kwargs):  # noqa: ANN001
        if type_ == __import__("socket").SOCK_DGRAM:
            return FakeUdp()
        return FakeTcp()

    with (
        patch("hostskeeper.session.knock.socket.socket", side_effect=fake_socket),
        patch("hostskeeper.session.knock.time.sleep") as slept,
    ):
        perform_knock(
            "192.0.2.1",
            [
                KnockStep(4011, "tcp"),
                KnockStep(5022, "udp"),
                KnockStep(6033, "tcp"),
            ],
            delay_ms=200,
            pause_ms=300,
        )
    assert seen == [("tcp", 4011), ("udp", 5022), ("tcp", 6033)]
    assert slept.call_count == 3
