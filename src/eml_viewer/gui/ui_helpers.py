"""Display helpers for untrusted email text and compact desktop layouts."""

from __future__ import annotations

import html
import re

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy


_DISPLAY_CONTROLS = re.compile(
    r"[\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u2028-\u202e\u2066-\u2069\ufeff]"
)


def display_safe_text(value: object) -> str:
    """Expose control/bidi characters without altering underlying email data."""
    return _DISPLAY_CONTROLS.sub(lambda match: f"\\u{ord(match.group()):04x}", str(value))


def safe_tooltip(value: object, *extra_lines: object) -> str:
    """Use only our own markup so attachment/header strings stay literal."""
    lines = (value, *extra_lines)
    return "<qt>" + "<br>".join(html.escape(display_safe_text(line)) for line in lines) + "</qt>"


def printer_icon(palette: QPalette, device_pixel_ratio: float = 1.0) -> QIcon:
    """Draw a palette-aware printer without shell lookups or external assets."""
    ratio = max(1.0, device_pixel_ratio)
    pixmap = QPixmap(round(20 * ratio), round(20 * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(palette.color(QPalette.ColorRole.ButtonText), 1.5))
    painter.drawRect(6, 2, 8, 5)
    painter.drawRoundedRect(3, 7, 14, 9, 2, 2)
    painter.fillRect(6, 12, 8, 6, palette.color(QPalette.ColorRole.Base))
    painter.drawRect(6, 12, 8, 6)
    painter.drawPoint(14, 10)
    painter.end()
    return QIcon(pixmap)


class ElidedLabel(QLabel):
    """A plain label that yields width to its layout and keeps a full tooltip."""

    def __init__(self, parent=None, *, mode=Qt.TextElideMode.ElideMiddle) -> None:
        super().__init__(parent)
        self._full_text = ""
        self._elide_mode = mode
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:
        self._full_text = display_safe_text(text)
        self.setToolTip(safe_tooltip(text))
        self.setAccessibleName(self._full_text)
        self._update_elision()

    def fullText(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elision()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if hasattr(self, "_full_text") and event.type() in {
            QEvent.Type.FontChange, QEvent.Type.ApplicationFontChange, QEvent.Type.StyleChange,
        }:
            self._update_elision()

    def _update_elision(self) -> None:
        available = max(0, self.contentsRect().width() - 4)
        super().setText(self.fontMetrics().elidedText(self._full_text, self._elide_mode, available))
