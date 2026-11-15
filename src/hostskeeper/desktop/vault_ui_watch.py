"""Notify open UI surfaces when the vault changes outside that surface (e.g. MCP)."""

from __future__ import annotations

import weakref
from typing import Any

# Weak refs so closed dialogs/panels do not keep the registry alive.
_listeners: set[weakref.ReferenceType[Any]] = set()


def register(listener: object) -> None:
    """Register an object with ``on_vault_externally_changed()``."""
    for ref in _listeners:
        if ref() is listener:
            return

    def _remove(ref: weakref.ReferenceType[Any]) -> None:
        _listeners.discard(ref)

    _listeners.add(weakref.ref(listener, _remove))


def notify_all() -> None:
    """Call listeners on the GUI thread (caller must already be on GUI thread)."""
    for ref in list(_listeners):
        obj = ref()
        if obj is None:
            continue
        fn = getattr(obj, "on_vault_externally_changed", None)
        if not callable(fn):
            continue
        try:
            fn()
        except Exception:  # noqa: BLE001 — one broken view must not block others
            pass
