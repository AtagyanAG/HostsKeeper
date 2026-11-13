"""Former web UI entry — redirects to desktop."""

from __future__ import annotations

import sys


def main() -> None:
    print(
        "HostsKeeper browser UI is retired. Launch desktop:\n"
        "  python -m hostskeeper\n"
        "  python -m hostskeeper.desktop",
        file=sys.stderr,
    )
    raise SystemExit(2)


if __name__ == "__main__":
    main()
