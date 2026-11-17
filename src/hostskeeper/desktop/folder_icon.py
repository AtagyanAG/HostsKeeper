"""Folder glyphs for group nodes: pale = empty, saturated = has children."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QTreeWidgetItem


def folder_icon(*, filled: bool) -> QIcon:
    """16×16 folder: empty is pale; non-empty uses saturated yellow."""
    size = 16
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if filled:
        tab = QColor(255, 210, 70)
        body = QColor(255, 190, 40)
        edge = QColor(196, 140, 20)
    else:
        tab = QColor(255, 240, 200)
        body = QColor(255, 230, 160)
        edge = QColor(210, 185, 120)
    painter.setPen(edge)
    painter.setBrush(tab)
    painter.drawRoundedRect(1, 2, 7, 4, 1, 1)
    painter.setBrush(body)
    painter.drawRoundedRect(1, 5, 14, 10, 1.5, 1.5)
    painter.end()
    return QIcon(pm)


def _draw_mcp_disabled_border(painter: QPainter, *, mcp_enabled: bool) -> None:
    if mcp_enabled:
        return
    painter.setPen(QPen(QColor(205, 55, 55), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(0, 0, 15, 15)


def note_icon(*, mcp_enabled: bool = False) -> QIcon:
    """16×16 document leaf; disabled MCP visibility has a thin red frame."""
    size = 16
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if mcp_enabled:
        fill = QColor(210, 230, 255)
        edge = QColor(70, 110, 170)
    else:
        fill = QColor(245, 245, 245)
        edge = QColor(120, 120, 120)
    painter.setPen(edge)
    painter.setBrush(fill)
    painter.drawRoundedRect(3, 1, 10, 14, 1.5, 1.5)
    painter.drawLine(5, 5, 11, 5)
    painter.drawLine(5, 8, 11, 8)
    painter.drawLine(5, 11, 9, 11)
    _draw_mcp_disabled_border(painter, mcp_enabled=mcp_enabled)
    painter.end()
    return QIcon(pm)


def host_icon(*, mcp_enabled: bool = False) -> QIcon:
    """16×16 host/server glyph; disabled MCP visibility has a thin red frame."""
    size = 16
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    edge = QColor(70, 100, 140)
    fill = QColor(180, 205, 235)
    face = QColor(230, 240, 250)
    painter.setPen(edge)
    painter.setBrush(fill)
    painter.drawRoundedRect(2, 1, 12, 10, 1.5, 1.5)
    painter.setBrush(face)
    painter.drawRect(4, 3, 8, 5)
    painter.drawLine(5, 13, 11, 13)
    painter.drawLine(8, 11, 8, 13)
    _draw_mcp_disabled_border(painter, mcp_enabled=mcp_enabled)
    painter.end()
    return QIcon(pm)


def script_icon(*, mcp_enabled: bool = True) -> QIcon:
    """16×16 shell/script glyph; disabled MCP visibility has a thin red frame."""
    size = 16
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    edge = QColor(40, 100, 70)
    fill = QColor(220, 245, 230)
    painter.setPen(edge)
    painter.setBrush(fill)
    painter.drawRoundedRect(2, 1, 12, 14, 1.5, 1.5)
    painter.drawLine(5, 5, 7, 7)
    painter.drawLine(7, 7, 5, 9)
    painter.drawLine(8, 11, 11, 11)
    _draw_mcp_disabled_border(painter, mcp_enabled=mcp_enabled)
    painter.end()
    return QIcon(pm)


def apply_group_folder_icons(
    item: QTreeWidgetItem,
    *,
    group_kinds: frozenset[str],
) -> None:
    """Set folder icon on group nodes from direct childCount (recursive)."""
    data = item.data(0, Qt.ItemDataRole.UserRole)
    kind = data.get("kind") if isinstance(data, dict) else None
    kind_key = getattr(kind, "value", kind)
    if kind_key in group_kinds:
        item.setIcon(0, folder_icon(filled=item.childCount() > 0))
    for i in range(item.childCount()):
        child = item.child(i)
        if child is not None:
            apply_group_folder_icons(child, group_kinds=group_kinds)
