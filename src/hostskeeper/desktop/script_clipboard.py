"""Clipboard helpers for Script entities (human UI copy)."""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication

from hostskeeper.vault.models import Script


def copy_script_to_clipboard(script: Script) -> None:
    """Copy script body only — user pastes wherever they need."""
    QGuiApplication.clipboard().setText(script.body)
