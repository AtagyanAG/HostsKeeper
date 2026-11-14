"""Application UI theme: system / light / dark."""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

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

# Classic Win10 default highlight (fallback if native style missing).
_FALLBACK_ACCENT = QColor(0, 120, 215)
_FALLBACK_ACCENT_TEXT = QColor(255, 255, 255)


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


def _windows_dwm_accent() -> QColor | None:
    """Windows accent from DWM (ABGR DWORD); None if unavailable."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AccentColor")
        if not isinstance(value, int):
            return None
        # AccentColor is 0xAABBGGRR
        return QColor(value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)
    except OSError:
        return None


def os_accent_colors() -> tuple[QColor, QColor]:
    """Accent as native Windows style used before Fusion (follows OS).

    ``QStyle.standardPalette()`` alone returns a classic navy Highlight; the
    real system tint appears on the app palette after ``setStyle`` to a
    windows* style. Prefer that; fall back to DWM AccentColor, then Win10 blue.
    """
    app = QApplication.instance()
    if app is not None:
        keys = {k.lower(): k for k in QStyleFactory.keys()}
        native = next(
            (
                keys[c]
                for c in ("windows11", "windowsvista", "windows")
                if c in keys
            ),
            None,
        )
        if native is not None:
            prev_style = app.style().objectName()
            prev_pal = QPalette(app.palette())
            try:
                app.setStyle(native)
                pal = app.palette()
                bg = QColor(pal.color(QPalette.ColorRole.Highlight))
                accent = QColor(pal.color(QPalette.ColorRole.Accent))
                if accent.isValid() and accent.name() not in ("#000000", "#000"):
                    bg = accent
                fg = QColor(pal.color(QPalette.ColorRole.HighlightedText))
                if not fg.isValid() or fg == bg:
                    fg = QColor(_FALLBACK_ACCENT_TEXT)
                return bg, fg
            finally:
                if prev_style:
                    app.setStyle(prev_style)
                app.setPalette(prev_pal)

    dwm = _windows_dwm_accent()
    if dwm is not None and dwm.isValid():
        return dwm, QColor(_FALLBACK_ACCENT_TEXT)
    return QColor(_FALLBACK_ACCENT), QColor(_FALLBACK_ACCENT_TEXT)


def _accent_checkable_qss(bg: QColor, fg: QColor) -> str:
    """Checked look for session MCP/Approve only (Fusion otherwise hides accent)."""
    border = QColor(bg).darker(115)
    return f"""
QPushButton#sessionMcpToggle:checked,
QPushButton#sessionApproveToggle:checked {{
    background-color: {bg.name()};
    color: {fg.name()};
    border: 1px solid {border.name()};
}}
QPushButton#sessionMcpToggle:checked:hover,
QPushButton#sessionApproveToggle:checked:hover {{
    background-color: {QColor(bg).lighter(110).name()};
    color: {fg.name()};
}}
"""


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
    accent_bg, accent_fg = os_accent_colors()
    parts = []
    if dark:
        parts.append(_DARK_EDITOR_QSS)
    parts.append(_accent_checkable_qss(accent_bg, accent_fg))
    app.setStyleSheet("\n".join(parts))
    syntax_edit.refresh_theme(dark=dark)


def wire_system_theme_watcher() -> None:
    """Follow OS light/dark; refresh accent for MCP/Approve on scheme change."""
    app = QApplication.instance()
    if app is None:
        return
    hints = app.styleHints()

    def _on_scheme(_scheme: Qt.ColorScheme) -> None:
        # Re-apply current theme so system dark/light and OS accent stay in sync.
        apply_app_theme(_current_theme)

    try:
        hints.colorSchemeChanged.connect(_on_scheme)
    except Exception:  # noqa: BLE001
        pass
