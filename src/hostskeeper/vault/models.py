"""Vault entity models (in-memory)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> UUID:
    return uuid4()


@dataclass
class Group:
    """Folder-like node for Hosts or Scripts tree (vault-persisted)."""

    name: str
    kind: str  # "hosts" | "scripts"
    id: UUID = field(default_factory=_new_id)
    parent_id: UUID | None = None
    # None = global tree (Hosts / template Scripts); set = host-local Scripts folder.
    host_id: UUID | None = None
    # UI-only: tree expand state (default expanded). Not exposed via MCP.
    expanded: bool = True
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "kind": self.kind,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "host_id": str(self.host_id) if self.host_id else None,
            "expanded": bool(self.expanded),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def to_mcp_dict(self) -> dict[str, Any]:
        data = self.to_dict()
        data.pop("expanded", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Group:
        return cls(
            id=UUID(data["id"]),
            name=data["name"],
            kind=data.get("kind") or "hosts",
            parent_id=UUID(data["parent_id"]) if data.get("parent_id") else None,
            host_id=UUID(data["host_id"]) if data.get("host_id") else None,
            expanded=bool(data.get("expanded", True)),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


@dataclass
class Host:
    name: str
    id: UUID = field(default_factory=_new_id)
    description: str | None = None
    # Free-form host Notes (OS, packages, runtimes, …) — Edit Host → Notes tab.
    profile: str | None = None
    tags: list[str] = field(default_factory=list)
    default_address_id: UUID | None = None
    default_credential_id: UUID | None = None
    group_id: UUID | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "profile": self.profile,
            "tags": list(self.tags),
            "default_address_id": str(self.default_address_id)
            if self.default_address_id
            else None,
            "default_credential_id": str(self.default_credential_id)
            if self.default_credential_id
            else None,
            "group_id": str(self.group_id) if self.group_id else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Host:
        return cls(
            id=UUID(data["id"]),
            name=data["name"],
            description=data.get("description"),
            profile=data.get("profile"),
            tags=list(data.get("tags") or []),
            default_address_id=UUID(data["default_address_id"])
            if data.get("default_address_id")
            else None,
            default_credential_id=UUID(data["default_credential_id"])
            if data.get("default_credential_id")
            else None,
            group_id=UUID(data["group_id"]) if data.get("group_id") else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


@dataclass
class Address:
    host_id: UUID
    host: str
    id: UUID = field(default_factory=_new_id)
    label: str | None = None
    port: int = 22
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    # Port knocking (TCP/UDP sequence) before SSH / launchers.
    knock_enabled: bool = False
    knock_steps: list[dict[str, Any]] = field(default_factory=list)
    knock_delay_ms: int = 200
    knock_pause_ms: int = 300
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    @property
    def knock_ports(self) -> list[int]:
        """Ports only (legacy helper); protocol ignored."""
        return [int(s.get("port", 0)) for s in self.knock_steps if s.get("port")]

    def to_dict(self) -> dict[str, Any]:
        steps = []
        for raw in self.knock_steps:
            port = int(raw.get("port", 0))
            proto = str(raw.get("protocol") or "tcp").lower()
            if proto not in ("tcp", "udp"):
                proto = "tcp"
            steps.append({"port": port, "protocol": proto})
        return {
            "id": str(self.id),
            "host_id": str(self.host_id),
            "label": self.label,
            "host": self.host,
            "port": self.port,
            "description": self.description,
            "tags": list(self.tags),
            "knock_enabled": bool(self.knock_enabled),
            "knock_steps": steps,
            # Legacy: ports-only list for older readers.
            "knock_ports": [s["port"] for s in steps],
            "knock_delay_ms": int(self.knock_delay_ms),
            "knock_pause_ms": int(self.knock_pause_ms),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Address:
        steps: list[dict[str, Any]] = []
        if data.get("knock_steps"):
            for item in data["knock_steps"]:
                if isinstance(item, dict):
                    steps.append(
                        {
                            "port": int(item.get("port", 0)),
                            "protocol": str(item.get("protocol") or "tcp").lower(),
                        }
                    )
                else:
                    steps.append({"port": int(item), "protocol": "tcp"})
        else:
            for item in data.get("knock_ports") or []:
                steps.append({"port": int(item), "protocol": "tcp"})
        return cls(
            id=UUID(data["id"]),
            host_id=UUID(data["host_id"]),
            label=data.get("label"),
            host=data["host"],
            port=int(data.get("port", 22)),
            description=data.get("description"),
            tags=list(data.get("tags") or []),
            knock_enabled=bool(data.get("knock_enabled", False)),
            knock_steps=steps,
            knock_delay_ms=int(data.get("knock_delay_ms", 200)),
            knock_pause_ms=int(data.get("knock_pause_ms", 300)),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


AUTH_PASSWORD = "password"
AUTH_KEY_PAIR = "key_pair"
AUTH_OPENSSH_CONFIG = "openssh_config"
AUTH_TYPES = (AUTH_PASSWORD, AUTH_KEY_PAIR, AUTH_OPENSSH_CONFIG)


def infer_auth_type(
    *,
    auth_type: str | None,
    password: str | None,
    private_key: str | None,
) -> str:
    if auth_type in AUTH_TYPES:
        return auth_type
    if private_key:
        return AUTH_KEY_PAIR
    if password:
        return AUTH_PASSWORD
    return AUTH_PASSWORD


@dataclass
class Credential:
    host_id: UUID
    username: str
    id: UUID = field(default_factory=_new_id)
    label: str | None = None
    auth_type: str = AUTH_PASSWORD
    password: str | None = None
    private_key: str | None = None
    passphrase: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        # Legacy constructors often set only private_key with default auth_type.
        if self.auth_type == AUTH_PASSWORD and not self.password and self.private_key:
            self.auth_type = AUTH_KEY_PAIR

    def __repr__(self) -> str:
        return (
            f"Credential(id={self.id!r}, host_id={self.host_id!r}, "
            f"label={self.label!r}, username={self.username!r}, "
            f"auth_type={self.auth_type!r}, "
            f"password={'***' if self.password else None}, "
            f"private_key={'***' if self.private_key else None}, "
            f"passphrase={'***' if self.passphrase else None}, "
            f"description={self.description!r}, tags={self.tags!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "host_id": str(self.host_id),
            "label": self.label,
            "username": self.username,
            "auth_type": self.auth_type,
            "password": self.password,
            "private_key": self.private_key,
            "passphrase": self.passphrase,
            "description": self.description,
            "tags": list(self.tags),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Credential:
        password = data.get("password")
        private_key = data.get("private_key")
        return cls(
            id=UUID(data["id"]),
            host_id=UUID(data["host_id"]),
            label=data.get("label"),
            username=data["username"],
            auth_type=infer_auth_type(
                auth_type=data.get("auth_type"),
                password=password,
                private_key=private_key,
            ),
            password=password,
            private_key=private_key,
            passphrase=data.get("passphrase"),
            description=data.get("description"),
            tags=list(data.get("tags") or []),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


@dataclass
class ScriptParameter:
    name: str
    description: str | None = None
    required: bool = True
    default: str | None = None
    # Human-only secret for local Run (PuTTY). Never exposed via MCP.
    user_value: str | None = None

    def __repr__(self) -> str:
        return (
            f"ScriptParameter(name={self.name!r}, description={self.description!r}, "
            f"required={self.required!r}, default={self.default!r}, "
            f"user_value={'***' if self.user_value is not None else None})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
            "default": self.default,
            "user_value": self.user_value,
        }

    def to_mcp_dict(self) -> dict[str, Any]:
        """Public parameter card for MCP (no user_value)."""
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
            "default": self.default,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScriptParameter:
        default = data.get("default")
        # On create (key omitted): seed user_value from default. Explicit null stays null.
        if "user_value" in data:
            user_value = data.get("user_value")
        else:
            user_value = default
        return cls(
            name=data["name"],
            description=data.get("description"),
            required=bool(data.get("required", True)),
            default=default,
            user_value=user_value,
        )

    @classmethod
    def from_mcp_dict(
        cls,
        data: dict[str, Any],
        *,
        preserve: ScriptParameter | None = None,
    ) -> ScriptParameter:
        """Build from MCP payload: ignore inbound user_value; keep existing if any."""
        cleaned = {k: v for k, v in data.items() if k != "user_value"}
        param = cls.from_dict(cleaned)
        if preserve is not None:
            param.user_value = preserve.user_value
        return param


@dataclass
class Note:
    """Markdown note leaf in Scripts trees (global or host-local)."""

    name: str
    body: str = ""
    id: UUID = field(default_factory=_new_id)
    group_id: UUID | None = None
    # None = template (global Scripts tree); set = host-local note.
    host_id: UUID | None = None
    # When True, note is visible/editable via MCP notes_* (no Approve).
    mcp_enabled: bool = False
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "body": self.body,
            "group_id": str(self.group_id) if self.group_id else None,
            "host_id": str(self.host_id) if self.host_id else None,
            "mcp_enabled": bool(self.mcp_enabled),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def to_mcp_dict(self) -> dict[str, Any]:
        return self.to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Note:
        return cls(
            id=UUID(data["id"]),
            name=data["name"],
            body=data.get("body") or "",
            group_id=UUID(data["group_id"]) if data.get("group_id") else None,
            host_id=UUID(data["host_id"]) if data.get("host_id") else None,
            mcp_enabled=bool(data.get("mcp_enabled", False)),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


@dataclass
class Script:
    name: str
    body: str
    id: UUID = field(default_factory=_new_id)
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    parameters: list[ScriptParameter] = field(default_factory=list)
    group_id: UUID | None = None
    # None = template (global Scripts tree); set = host-local script.
    host_id: UUID | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "tags": list(self.tags),
            "body": self.body,
            "parameters": [p.to_dict() for p in self.parameters],
            "group_id": str(self.group_id) if self.group_id else None,
            "host_id": str(self.host_id) if self.host_id else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def to_mcp_dict(self) -> dict[str, Any]:
        data = self.to_dict()
        data["parameters"] = [p.to_mcp_dict() for p in self.parameters]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Script:
        return cls(
            id=UUID(data["id"]),
            name=data["name"],
            description=data.get("description"),
            tags=list(data.get("tags") or []),
            body=data["body"],
            parameters=[
                ScriptParameter.from_dict(p) for p in (data.get("parameters") or [])
            ],
            group_id=UUID(data["group_id"]) if data.get("group_id") else None,
            host_id=UUID(data["host_id"]) if data.get("host_id") else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )
