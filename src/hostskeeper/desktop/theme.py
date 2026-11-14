"""Application UI theme: system / light / dark."""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ThemeName = Literal["system", "light", "dark"]
THEME_CHOICES: tuple[ThemeName, ...] = ("system", "light", "dark")

# Semi-transparent gray for script editors on dark theme.
_DARK_EDITOR_QSS = """
QPlainTextEdit {
    background-color: rgba(78, 78, 84, 210);
    color: #EAEAEA;
    selection-background-color: #3A5F8A;
    selection-color: #FFFFFF;
}
"""


def normalize_theme(value: str | None) -> ThemeName:
    raw = (value or "system").strip().lower()
    if raw in THEME_CHOICES:
        return raw  # type: ignore[return-value]
    return "system"


def is_system_dark() -> bool:
    app = QApplication.instance()
    if app is None:
        return False
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # noqa: BLE001
        return app.palette().color(QPalette.ColorRole.Window).lightness() < 128


def effective_dark(theme: str | None) -> bool:
    name = normalize_theme(theme)
    if name == "dark":
        return True
    if name == "light":
        return False
    return is_system_dark()


def _light_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(240, 240, 240))
    p.setColor(QPalette.ColorRole.WindowText, QColor(30, 30, 30))
    p.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(245, 245, 245))
    p.setColor(QPalette.ColorRole.Text, QColor(30, 30, 30))
    p.setColor(QPalette.ColorRole.Button, QColor(240, 240, 240))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(30, 30, 30))
    p.setColor(QPalette.ColorRole.Highlight, QColor(0, 120, 215))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 220))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(30, 30, 30))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(120, 120, 120))
    p.setColor(QPalette.ColorRole.Link, QColor(0, 102, 204))
    return p


def _dark_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(45, 45, 48))
    p.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.Base, QColor(37, 37, 38))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 48))
    p.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.Button, QColor(55, 55, 58))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.Highlight, QColor(0, 99, 177))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(60, 60, 60))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(140, 140, 140))
    p.setColor(QPalette.ColorRole.Link, QColor(100, 180, 255))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(120, 120, 120))
    p.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(120, 120, 120)
    )
    return p


_current_theme: ThemeName = "system"


def current_theme() -> ThemeName:
    return _current_theme


def apply_app_theme(theme: str | None) -> None:
    """Apply Fusion palette + editor QSS; refresh syntax highlighters."""
    global _current_theme
    from hostskeeper.desktop import syntax_edit

    app = QApplication.instance()
    if app is None:
        return
    name = normalize_theme(theme)
    _current_theme = name
    dark = effective_dark(name)
    app.setStyle("Fusion")
    app.setPalette(_dark_palette() if dark else _light_palette())
    app.setStyleSheet(_DARK_EDITOR_QSS if dark else "")
    syntax_edit.refresh_theme(dark=dark)


def wire_system_theme_watcher() -> None:
    """When theme=system, follow OS light/dark changes."""
    app = QApplication.instance()
    if app is None:
        return
    hints = app.styleHints()

    def _on_scheme(_scheme: Qt.ColorScheme) -> None:
        if _current_theme == "system":
            apply_app_theme("system")

    try:
        hints.colorSchemeChanged.connect(_on_scheme)
    except Exception:  # noqa: BLE001
        pass
