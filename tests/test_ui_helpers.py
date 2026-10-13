from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from eml_viewer.gui import dialogs
from eml_viewer.gui.theme import _ensure_highlight_contrast
from eml_viewer.gui.ui_helpers import display_safe_text, printer_icon, safe_tooltip


def test_untrusted_single_line_text_exposes_hidden_controls_without_markup() -> None:
    raw = "<b>invoice</b>\u202eexe.pdf\u2028\u200f\u061c\ufeff"
    displayed = display_safe_text(raw)
    assert "\\u202e" in displayed and "\\u2028" in displayed
    assert "\\u200f" in displayed and "\\u061c" in displayed and "\\ufeff" in displayed
    assert "&lt;b&gt;invoice&lt;/b&gt;" in safe_tooltip(raw)
    assert "<br>" in safe_tooltip(raw, "Declared type")
    assert raw.endswith("\ufeff")  # Original filename remains suitable for existing services.


def test_error_dialog_keeps_untrusted_markup_literal() -> None:
    app = QApplication.instance() or QApplication([])
    seen = []

    def record(dialog):
        seen.append((dialog.text(), dialog.textFormat(), dialog.icon()))
        return QMessageBox.StandardButton.Ok

    message = "<img src='file:///private'>\nfilename failed"
    with patch.object(QMessageBox, "exec", record):
        dialogs.show_error(None, "Error", message)
    assert seen == [(message, Qt.TextFormat.PlainText, QMessageBox.Icon.Critical)]
    app.processEvents()


def test_attachment_warning_is_literal_and_cancel_is_default() -> None:
    app = QApplication.instance() or QApplication([])
    seen = []

    def cancel(dialog):
        seen.append((dialog.text(), dialog.textFormat(),
                     dialog.standardButton(dialog.defaultButton()),
                     dialog.standardButton(dialog.escapeButton())))
        return QMessageBox.StandardButton.No

    message = "<b>report & data.exe</b>"
    with patch.object(QMessageBox, "exec", cancel):
        assert not dialogs.ask_warning_yes_no(None, "Warning", message)
    assert seen == [(message, Qt.TextFormat.PlainText,
                     QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)]
    app.processEvents()


def test_native_accent_text_remains_readable_and_high_dpi_icon_keeps_logical_size() -> None:
    app = QApplication.instance() or QApplication([])
    palette = QPalette(app.palette())
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        palette.setColor(group, QPalette.ColorRole.Highlight, QColor("#81c9ed"))
        palette.setColor(group, QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    _ensure_highlight_contrast(palette)
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        assert palette.color(group, QPalette.ColorRole.Highlight) == QColor("#81c9ed")
        assert palette.color(group, QPalette.ColorRole.HighlightedText) == QColor("#000000")
    icon = printer_icon(palette, device_pixel_ratio=1.5)
    pixmap = icon.pixmap(QSize(20, 20), 1.5)
    assert not pixmap.isNull()
    assert pixmap.deviceIndependentSize().width() == 20
