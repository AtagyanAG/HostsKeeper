"""CLI entry: ``python -m hostskeeper``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from hostskeeper import __version__
from hostskeeper.runtime.stdio_fix import ensure_stdio


def main(argv: list[str] | None = None) -> int:
    ensure_stdio()
    parser = argparse.ArgumentParser(description="HostsKeeper")
    parser.add_argument(
        "--version",
        "-V",
        action="store_true",
        help="Print version and exit",
    )
    parser.add_argument(
        "--ui",
        choices=("qt", "web"),
        default="qt",
        help="UI frontend (default: qt). web is retired.",
    )
    parser.add_argument(
        "--vault",
        default=os.environ.get("HOSTSKEEPER_VAULT")
        or os.environ.get("HOSTSSAFE_VAULT"),
        help="Vault path hint for the Vaults list (default: last used / %%APPDATA%%\\HostsKeeper)",
    )
    parser.add_argument("--mcp-host", default="0.0.0.0")
    parser.add_argument("--mcp-port", type=int, default=8765)
    parser.add_argument(
        "--mcp-key",
        default=os.environ.get("HOSTSKEEPER_MCP_KEY")
        or os.environ.get("HOSTSSAFE_MCP_KEY"),
        help="Stable LAN MCP app key (default: ~/.hostskeeper/mcp.key or env)",
    )
    args = parser.parse_args(argv if argv is not None else None)

    if args.version:
        print(f"HostsKeeper {__version__}")
        return 0

    if args.ui == "web":
        print(
            "Browser UI was retired (stage 14). Use: python -m hostskeeper",
            file=sys.stderr,
        )
        return 2

    from hostskeeper.desktop import run_desktop

    return run_desktop(
        vault_path=Path(args.vault) if args.vault else None,
        mcp_host=args.mcp_host,
        mcp_port=args.mcp_port,
        mcp_key=args.mcp_key,
    )


if __name__ == "__main__":
    raise SystemExit(main())
