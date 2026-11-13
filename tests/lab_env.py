"""Optional live-SSH lab settings via environment (no private paths in repo).

Integration tests skip unless ``HOSTSKEEPER_TEST_SSH_KEY`` (or legacy
``HOSTSSAFE_TEST_SSH_KEY``) points to an existing key file.
"""

from __future__ import annotations

import os
from pathlib import Path


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


# Documentation / placeholder defaults — not a real lab.
HOST = _env("HOSTSKEEPER_TEST_SSH_HOST", "HOSTSSAFE_TEST_SSH_HOST", default="127.0.0.1")
PORT = int(_env("HOSTSKEEPER_TEST_SSH_PORT", "HOSTSSAFE_TEST_SSH_PORT", default="22"))
USER = _env("HOSTSKEEPER_TEST_SSH_USER", "HOSTSSAFE_TEST_SSH_USER", default="labuser")
KEY_PATH = Path(
    _env("HOSTSKEEPER_TEST_SSH_KEY", "HOSTSSAFE_TEST_SSH_KEY", default="")
)
# Vault Host.name used when seeding a lab entry (alias prefix).
VAULT_HOST_NAME = "lab-host"


def lab_key_available() -> bool:
    return bool(str(KEY_PATH)) and KEY_PATH.is_file()
