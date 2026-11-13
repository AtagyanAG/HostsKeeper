"""Create a disposable demo vault for README / marketing screenshots.

Uses documentation-only IPs (RFC 5737) and placeholder credentials — not a real lab.
Vault file defaults under ``data/`` (gitignored).

Usage (from repo root)::

    .\\.venv\\Scripts\\python.exe scripts\\seed_demo_vault.py
    .\\.venv\\Scripts\\python.exe -m hostskeeper --vault data\\demo-screenshots.vault

Password: ``demo``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from hostskeeper.vault import (  # noqa: E402
    Address,
    Credential,
    Group,
    Host,
    Script,
    ScriptParameter,
    Vault,
)
from hostskeeper.vault.errors import VaultExistsError  # noqa: E402

DEFAULT_PATH = _ROOT / "data" / "demo-screenshots.vault"
DEFAULT_PASSWORD = "demo"


def _seed(vault: Vault) -> None:
    lab = vault.add_group(Group(name="Lab", kind="hosts"))
    prod = vault.add_group(Group(name="Production", kind="hosts"))

    # --- Lab hosts ---
    web = vault.add_host(
        Host(
            name="lab-web-1",
            description="Demo web VM (screenshots only)",
            tags=["lab", "web"],
            group_id=lab.id,
            profile=(
                "# lab-web-1\n\n"
                "- **OS:** Rocky Linux 9 (demo)\n"
                "- **Role:** nginx front\n"
                "- **Notes:** fictional host for UI screenshots\n"
            ),
        )
    )
    web_addr = vault.add_address(
        Address(
            host_id=web.id,
            host="192.0.2.10",
            port=22,
            label="lan",
            tags=["demo"],
        )
    )
    web_cred = vault.add_credential(
        Credential(
            host_id=web.id,
            username="demo",
            password="demo-only-not-real",
            label="password",
        )
    )
    web.default_address_id = web_addr.id
    web.default_credential_id = web_cred.id
    vault.update_host(web)

    db = vault.add_host(
        Host(
            name="lab-db-1",
            description="Demo database VM",
            tags=["lab", "db"],
            group_id=lab.id,
            profile=(
                "# lab-db-1\n\n"
                "- **OS:** Debian 12 (demo)\n"
                "- **Role:** PostgreSQL\n"
            ),
        )
    )
    db_addr = vault.add_address(
        Address(host_id=db.id, host="192.0.2.20", port=22, label="lan")
    )
    db_cred = vault.add_credential(
        Credential(
            host_id=db.id,
            username="demo",
            password="demo-only-not-real",
            label="password",
        )
    )
    db.default_address_id = db_addr.id
    db.default_credential_id = db_cred.id
    vault.update_host(db)

    # --- Production (looks fuller in tree; still fake) ---
    edge = vault.add_host(
        Host(
            name="prod-edge-1",
            description="Edge proxy (fictional)",
            tags=["prod", "edge"],
            group_id=prod.id,
            profile="# prod-edge-1\n\nPlaceholder for screenshots.\n",
        )
    )
    edge_addr = vault.add_address(
        Address(
            host_id=edge.id,
            host="198.51.100.10",
            port=22,
            label="mgmt",
            knock_enabled=True,
            knock_steps=[
                {"proto": "tcp", "port": 7000},
                {"proto": "udp", "port": 8000},
                {"proto": "tcp", "port": 9000},
            ],
            knock_delay_ms=200,
        )
    )
    edge_cred = vault.add_credential(
        Credential(
            host_id=edge.id,
            username="deploy",
            password="demo-only-not-real",
            label="deploy",
        )
    )
    edge.default_address_id = edge_addr.id
    edge.default_credential_id = edge_cred.id
    vault.update_host(edge)

    # --- Template scripts (global Scripts tree) ---
    tpl_ops = vault.add_group(Group(name="Ops", kind="scripts"))
    vault.add_script(
        Script(
            name="uptime",
            body="uptime",
            description="Show load averages",
            tags=["ops"],
            group_id=tpl_ops.id,
        )
    )
    vault.add_script(
        Script(
            name="disk-free",
            body="df -h {{mount}}",
            description="Disk free space",
            tags=["ops"],
            group_id=tpl_ops.id,
            parameters=[
                ScriptParameter(
                    name="mount",
                    required=False,
                    default="/",
                    description="Mount point",
                )
            ],
        )
    )
    vault.add_script(
        Script(
            name="whoami",
            body="whoami; id",
            description="Current user",
            tags=["ops"],
        )
    )

    # --- Host-local scripts on lab-web-1 ---
    host_grp = vault.add_group(
        Group(name="Maintenance", kind="scripts", host_id=web.id)
    )
    vault.add_script(
        Script(
            name="nginx-status",
            body="systemctl status nginx --no-pager | head -n 20",
            description="Quick nginx status (demo)",
            host_id=web.id,
            group_id=host_grp.id,
            tags=["web"],
        )
    )
    vault.add_script(
        Script(
            name="reload-nginx",
            body="echo 'demo: would reload nginx'",
            description="Safe demo stub",
            host_id=web.id,
            group_id=host_grp.id,
            tags=["web"],
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed HostsKeeper demo vault")
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_PATH,
        help=f"Vault path (default: {DEFAULT_PATH})",
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help=f"Vault password (default: {DEFAULT_PASSWORD!r})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing vault file",
    )
    args = parser.parse_args(argv)

    path: Path = args.path
    if path.exists():
        if not args.force:
            print(f"Vault already exists: {path}", file=sys.stderr)
            print("Re-run with --force to recreate.", file=sys.stderr)
            return 2
        path.unlink()

    try:
        vault = Vault.create(path, args.password)
    except VaultExistsError as exc:
        print(exc, file=sys.stderr)
        return 2

    _seed(vault)
    vault.lock()

    print(f"Created: {path.resolve()}")
    print(f"Password: {args.password}")
    print()
    print("Open UI:")
    print(f'  python -m hostskeeper --vault "{path}"')
    print("Then: Connect vault → password above. Do not commit this file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
