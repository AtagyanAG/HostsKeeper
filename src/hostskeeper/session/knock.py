"""Client-side TCP/UDP port knocking before SSH connect."""

from __future__ import annotations

import socket
import time
from collections.abc import Sequence
from dataclasses import dataclass


PROTO_TCP = "tcp"
PROTO_UDP = "udp"
_PROTOCOLS = frozenset({PROTO_TCP, PROTO_UDP})


@dataclass(frozen=True)
class KnockStep:
    port: int
    protocol: str = PROTO_TCP

    def __post_init__(self) -> None:
        port = int(self.port)
        proto = (self.protocol or PROTO_TCP).strip().lower()
        if not (1 <= port <= 65535):
            raise ValueError(f"invalid knock port: {port}")
        if proto not in _PROTOCOLS:
            raise ValueError(f"invalid knock protocol: {proto}")
        object.__setattr__(self, "port", port)
        object.__setattr__(self, "protocol", proto)

    def to_dict(self) -> dict[str, int | str]:
        return {"port": int(self.port), "protocol": self.protocol}

    @classmethod
    def from_dict(cls, data: dict[str, object] | int) -> KnockStep:
        if isinstance(data, int):
            return cls(port=data, protocol=PROTO_TCP)
        port = int(data.get("port", 0))  # type: ignore[arg-type]
        proto = str(data.get("protocol") or PROTO_TCP)
        return cls(port=port, protocol=proto)


def parse_knock_sequence(text: str) -> list[KnockStep]:
    """Parse ``4011,5022:udp,6033`` (bare port = tcp)."""
    raw = (text or "").replace(";", ",").replace("|", ",").replace("\n", ",")
    steps: list[KnockStep] = []
    for part in raw.replace(",", " ").split():
        token = part.strip()
        if not token:
            continue
        if ":" in token:
            port_s, proto_s = token.rsplit(":", 1)
            steps.append(KnockStep(port=int(port_s), protocol=proto_s))
        else:
            steps.append(KnockStep(port=int(token), protocol=PROTO_TCP))
    return steps


def format_knock_sequence(steps: Sequence[KnockStep]) -> str:
    parts: list[str] = []
    for step in steps:
        if step.protocol == PROTO_TCP:
            parts.append(str(step.port))
        else:
            parts.append(f"{step.port}:{step.protocol}")
    return ",".join(parts)


# Back-compat aliases used by older call sites / tests.
def parse_knock_ports(text: str) -> list[int]:
    return [s.port for s in parse_knock_sequence(text)]


def format_knock_ports(ports: Sequence[int]) -> str:
    return format_knock_sequence([KnockStep(port=int(p)) for p in ports])


def perform_knock(
    hostname: str,
    steps: Sequence[KnockStep] | Sequence[int],
    *,
    delay_ms: int = 200,
    pause_ms: int = 300,
    connect_timeout_sec: float = 0.4,
) -> None:
    """Send knock sequence (TCP connect and/or UDP datagram), then pause.

    Failed TCP connects are expected; they still deliver SYN.
    Does not log hostname or ports.
    """
    host = (hostname or "").strip()
    if not host:
        raise ValueError("hostname required for knock")
    seq: list[KnockStep] = []
    for item in steps:
        if isinstance(item, KnockStep):
            seq.append(item)
        else:
            seq.append(KnockStep(port=int(item), protocol=PROTO_TCP))
    if not seq:
        return
    delay = max(0, int(delay_ms)) / 1000.0
    pause = max(0, int(pause_ms)) / 1000.0
    timeout = max(0.05, float(connect_timeout_sec))
    for index, step in enumerate(seq):
        if step.protocol == PROTO_UDP:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.sendto(b"", (host, step.port))
            except OSError:
                pass
            finally:
                sock.close()
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            try:
                sock.connect((host, step.port))
            except OSError:
                pass
            finally:
                sock.close()
        if index + 1 < len(seq) and delay > 0:
            time.sleep(delay)
    if pause > 0:
        time.sleep(pause)


def perform_tcp_knock(
    hostname: str,
    ports: Sequence[int],
    *,
    delay_ms: int = 200,
    pause_ms: int = 300,
    connect_timeout_sec: float = 0.4,
) -> None:
    """Backward-compatible TCP-only wrapper."""
    perform_knock(
        hostname,
        [KnockStep(port=int(p), protocol=PROTO_TCP) for p in ports],
        delay_ms=delay_ms,
        pause_ms=pause_ms,
        connect_timeout_sec=connect_timeout_sec,
    )
