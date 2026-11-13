"""``python -m hostskeeper.desktop``."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from hostskeeper.desktop.app import run_desktop


def main() -> None:
    parser = argparse.ArgumentParser(description="HostsKeeper desktop (PySide6)")
    parser.add_argument(
        "--vault",
        default=os.environ.get("HOSTSKEEPER_VAULT")
        or os.environ.get("HOSTSSAFE_VAULT"),
        help="Vault path hint (default: last used / %%APPDATA%%\\HostsKeeper)",
    )
    parser.add_argument("--mcp-host", default="0.0.0.0")
    parser.add_argument("--mcp-port", type=int, default=8765)
    parser.add_argument(
        "--mcp-key",
        default=os.environ.get("HOSTSKEEPER_MCP_KEY")
        or os.environ.get("HOSTSSAFE_MCP_KEY"),
        help="Stable LAN MCP app key",
    )
    args = parser.parse_args()
    raise SystemExit(
        run_desktop(
            vault_path=Path(args.vault) if args.vault else None,
            mcp_host=args.mcp_host,
            mcp_port=args.mcp_port,
            mcp_key=args.mcp_key,
        )
    )


if __name__ == "__main__":
    main()
