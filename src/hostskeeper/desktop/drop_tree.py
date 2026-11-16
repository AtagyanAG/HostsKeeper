"""QTreeWidget that reports drag-and-drop reparent requests without mutating itself."""

from __future__ import annotations

import json

from PySide6.QtCore import QByteArray, QMimeData, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QProxyStyle,
    QStyle,
    QStyleOption,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)


HOSTSKEEPER_NODE_MIME = "application/x-hostskeeper-node"
_LEGACY_NODE_MIME = "application/x-hostssafe-node"
_NODE_MIMES = (HOSTSKEEPER_NODE_MIME, _LEGACY_NODE_MIME)
# Hierarchy guides: ~half as visible as solid mid-gray (alpha ≈ 0.5).
_GUIDE_COLOR = QColor(180, 180, 180, 128)


class _TreeGuideStyle(QProxyStyle):
    """Draw faint vertical/horizontal guides in the tree branch column."""

    def drawPrimitive(  # noqa: N802
        self,
        element: QStyle.PrimitiveElement,
        option: QStyleOption,
        painter: QPainter,
        widget: QWidget | None = None,
    ) -> None:
        if element == QStyle.PrimitiveElement.PE_IndicatorBranch:
            rect = option.rect
            mid_x = rect.center().x()
            mid_y = rect.center().y()
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setPen(QPen(_GUIDE_COLOR, 1))
            state = option.state
            has_sibling = bool(state & QStyle.StateFlag.State_Sibling)
            has_children = bool(state & QStyle.StateFlag.State_Children)
            is_open = bool(state & QStyle.StateFlag.State_Open)
            is_item = bool(state & QStyle.StateFlag.State_Item)
            # Full vertical: more siblings below, or open folder continuing down.
            if has_sibling or (has_children and is_open):
                painter.drawLine(mid_x, rect.top(), mid_x, rect.bottom())
            elif is_item or has_children:
                # End of sibling list / closed parent: stem down to mid.
                painter.drawLine(mid_x, rect.top(), mid_x, mid_y)
            if is_item:
                painter.drawLine(mid_x, mid_y, rect.right(), mid_y)
            painter.restore()
        super().drawPrimitive(element, option, painter, widget)


class DropTreeWidget(QTreeWidget):
    """DnD that notifies the owner; tree is rebuilt from the persisted model."""

    reparent_requested = Signal(object, object)  # source item, target item|None
    foreign_drop_requested = Signal(object, object)  # payload dict, target item|None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        # DragDrop + CopyAction: avoid Qt Move cleanup deleting items after we
        # rebuild the tree in the reparent handler (corrupts Hosts/Vault roots).
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setIndentation(18)
        self.setStyle(_TreeGuideStyle())

    def mimeTypes(self) -> list[str]:  # noqa: N802
        return [HOSTSKEEPER_NODE_MIME, _LEGACY_NODE_MIME, *super().mimeTypes()]

    def _has_node_mime(self, mime) -> bool:
        return any(mime.hasFormat(name) for name in _NODE_MIMES)

    def _node_payload(self, mime) -> dict | None:
        for name in _NODE_MIMES:
            if not mime.hasFormat(name):
                continue
            raw = bytes(mime.data(name)).decode("utf-8")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return None
            return data if isinstance(data, dict) else None
        return None

    def mimeData(self, items: list[QTreeWidgetItem]) -> QMimeData:  # noqa: N802
        md = super().mimeData(items)
        if items:
            data = items[0].data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, dict) and "id" in data:
                payload = {
                    "kind": data.get("kind"),
                    "id": str(data["id"]),
                    "host_id": (
                        str(data["host_id"])
                        if data.get("host_id") is not None
                        else None
                    ),
                    "scope": data.get("scope"),
                    "group_id": (
                        str(data["group_id"])
                        if data.get("group_id") is not None
                        else None
                    ),
                }
                md.setData(
                    HOSTSKEEPER_NODE_MIME,
                    QByteArray(json.dumps(payload).encode("utf-8")),
                )
        return md

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._has_node_mime(event.mimeData()) or event.source() is self:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if self._has_node_mime(event.mimeData()) or event.source() is self:
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        target: QTreeWidgetItem | None = self.itemAt(pos)
        source_widget = event.source()
        if source_widget is not self and self._has_node_mime(event.mimeData()):
            payload = self._node_payload(event.mimeData())
            if payload is None:
                event.ignore()
                return
            self.foreign_drop_requested.emit(payload, target)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        sources = self.selectedItems()
        if not sources:
            event.ignore()
            return
        self.reparent_requested.emit(sources[0], target)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        # Do not call super(): owner refreshes tree from persisted model.
