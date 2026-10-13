from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from eml_viewer.gui.i18n import set_language
from eml_viewer.gui.attachment_widgets import AttachmentPanel
from eml_viewer.models.attachment_data import AttachmentInfo


class AttachmentPanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        set_language("en")
        self.panel = AttachmentPanel()
        self.panel.resize(820, 300)
        self.panel.show()
        self.attachments = [
            AttachmentInfo(index=10, filename="a.txt", content_type="text/plain", size=1024),
            AttachmentInfo(index=20, filename="b.pdf", content_type="application/pdf", size=2048),
            AttachmentInfo(index=30, filename="c.png", content_type="image/png", size=3072),
        ]
        self.panel.set_attachments(self.attachments)
        self.app.processEvents()

    def tearDown(self) -> None:
        self.panel.close()
        set_language("ko")

    def test_three_columns_selection_actions_and_bulk_save(self) -> None:
        table = self.panel._table
        self.assertEqual(table.columnCount(), 3)
        self.assertEqual(table.selectionMode(), table.SelectionMode.ExtendedSelection)
        self.assertFalse(table.isSortingEnabled())
        self.assertFalse(self.panel.selected_attachments())
        save_spy = QSignalSpy(self.panel.save_requested)

        self.panel._save_all_button.click()

        self.assertEqual(save_spy.count(), 1)
        self.assertEqual(save_spy.at(0)[0], self.attachments)
        self.assertFalse(self.panel._open_button.isEnabled())
        self.assertFalse(self.panel._save_button.isEnabled())

    def test_click_ctrl_shift_ctrl_a_and_escape_use_native_extended_selection(self) -> None:
        table = self.panel._table
        first = table.visualRect(table.model().index(0, 0)).center()
        second = table.visualRect(table.model().index(1, 0)).center()
        third = table.visualRect(table.model().index(2, 0)).center()

        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=second)
        self.assertEqual(self.panel.selected_attachments(), [self.attachments[1]])
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier, pos=third)
        self.assertEqual(self.panel.selected_attachments(), self.attachments[1:])
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ShiftModifier, pos=first)
        self.assertEqual(self.panel.selected_attachments(), self.attachments)

        table.setFocus()
        QTest.keyClick(table, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.panel.selected_attachments(), self.attachments)
        QTest.keyClick(table, Qt.Key.Key_Escape)
        self.assertEqual(self.panel.selected_attachments(), [])

    def test_single_attachment_preselects_without_emitting_and_session_collapse_survives_empty(self) -> None:
        opens = QSignalSpy(self.panel.open_requested)
        saves = QSignalSpy(self.panel.save_requested)
        self.panel._toggle_button.click()
        self.assertTrue(self.panel._table.isHidden())
        self.assertFalse(self.panel._command_row.isHidden())
        self.assertTrue(self.panel._save_all_button.isVisible())

        self.panel.set_attachments([])
        self.panel.set_attachments([self.attachments[0]])

        self.assertTrue(self.panel._table.isHidden())
        self.assertEqual(self.panel.selected_attachments(), [self.attachments[0]])
        self.assertEqual(self.panel._table.currentIndex().row(), 0)
        self.assertEqual(opens.count(), 0)
        self.assertEqual(saves.count(), 0)

    def test_activation_opens_once_for_enter_and_double_click(self) -> None:
        table = self.panel._table
        spy = QSignalSpy(self.panel.open_requested)
        table.setCurrentCell(0, 0)
        table.setFocus()
        QTest.keyClick(table, Qt.Key.Key_Return)
        self.assertEqual(spy.count(), 1)
        self.assertEqual(spy.at(0)[0], [self.attachments[0]])

        cell = table.visualRect(table.model().index(1, 0)).center()
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=cell)
        QTest.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=cell)
        self.assertEqual(spy.count(), 2)
        self.assertEqual(spy.at(1)[0], [self.attachments[1]])

    def test_safe_display_type_label_and_tooltips(self) -> None:
        spoofed = AttachmentInfo(40, "report.pdf.exe", "application/pdf", 12)
        bidi = AttachmentInfo(41, "invoice\u202etxt.pdf", "application/pdf", 12)
        self.panel.set_attachments([spoofed, bidi])

        self.assertEqual(self.panel._table.item(0, 1).text(), "Program (EXE)")
        self.assertIn("application/pdf", self.panel._table.item(0, 1).toolTip())
        self.assertIn("differs", self.panel._table.item(0, 1).toolTip())
        self.assertNotIn("\\u000a", self.panel._table.item(0, 1).toolTip())
        self.assertIn("\\u202e", self.panel._table.item(1, 0).text())
        self.assertEqual(self.panel._table.item(1, 1).text(), "PDF")

        trailing = AttachmentInfo(44, "evil.exe. ", "application/octet-stream", 1)
        self.panel.set_attachments([trailing])
        self.assertEqual(self.panel._table.item(0, 1).text(), "Program (EXE)")
        self.assertNotIn("differs", self.panel._table.item(0, 1).toolTip())
        zip_alias = AttachmentInfo(45, "bundle.zip", "application/x-zip-compressed", 1)
        self.panel.set_attachments([zip_alias])
        self.assertEqual(self.panel._table.item(0, 1).text(), "Archive")
        self.assertNotIn("differs", self.panel._table.item(0, 1).toolTip())

        long_filename = "very-long-name-" * 12 + ".pdf"
        long_attachment = AttachmentInfo(43, long_filename, "application/pdf", 1)
        self.panel.set_attachments([long_attachment])
        self.assertEqual(self.panel._table.textElideMode(), Qt.TextElideMode.ElideMiddle)
        self.assertIn(long_filename, self.panel._table.item(0, 0).toolTip())

        literal_markup = AttachmentInfo(42, "<b>x</b>.pdf", "application/pdf", 1)
        self.panel.set_attachments([literal_markup])
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", self.panel._table.item(0, 0).toolTip())

    def test_three_rows_fit_and_program_warning_tracks_light_and_dark_palettes(self) -> None:
        fonts = QFontDatabase.families()
        if "Segoe UI" in fonts:
            self.panel.setFont(QFont("Segoe UI", 9))
        self.panel.resize(820, 650)
        self.panel.set_attachments([
            AttachmentInfo(70, "one.exe", "application/x-msdownload", 1),
            AttachmentInfo(71, "two.pdf", "application/pdf", 2),
            AttachmentInfo(72, "three.txt", "text/plain", 3),
        ])
        self.panel.show()
        self.app.processEvents()
        table = self.panel._table
        self.assertEqual(table.verticalScrollBar().maximum(), 0)
        self.assertGreaterEqual(table.visualRect(table.model().index(2, 0)).bottom(), 0)
        self.assertLess(table.visualRect(table.model().index(2, 0)).bottom(), table.viewport().height())

        palette = table.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        table.setPalette(palette)
        QApplication.sendEvent(self.panel, QEvent(QEvent.Type.StyleChange))
        self.app.processEvents()
        light_warning = table.item(0, 1).foreground().color()
        self.assertNotEqual(light_warning, QColor("#ffffff"))
        self.assertLess(light_warning.lightness(), 128)

        palette.setColor(QPalette.ColorRole.Base, QColor("#202225"))
        table.setPalette(palette)
        QApplication.sendEvent(self.panel, QEvent(QEvent.Type.StyleChange))
        self.app.processEvents()
        dark_warning = table.item(0, 1).foreground().color()
        self.assertNotEqual(dark_warning, QColor("#202225"))
        self.assertGreater(dark_warning.lightness(), 128)
        self.assertEqual(table.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertIsNone(table.item(1, 1).data(Qt.ItemDataRole.ForegroundRole))

    def test_switching_mail_clears_stale_current_row_and_scroll_position(self) -> None:
        many = [
            AttachmentInfo(index, f"file-{index}.txt", "text/plain", index)
            for index in range(8)
        ]
        self.panel.set_attachments(many)
        table = self.panel._table
        table.setCurrentIndex(table.model().index(7, 0))
        table.scrollTo(table.model().index(7, 0), table.ScrollHint.PositionAtBottom)
        self.app.processEvents()
        self.assertGreater(table.verticalScrollBar().value(), 0)

        self.panel.set_attachments(self.attachments)
        self.app.processEvents()
        self.assertFalse(table.currentIndex().isValid())
        self.assertEqual(table.verticalScrollBar().value(), 0)
        opened = QSignalSpy(self.panel.open_requested)
        table.setFocus()
        QTest.keyClick(table, Qt.Key.Key_Return)
        self.assertEqual(opened.count(), 0)
        self.assertFalse(self.panel.selected_attachments())

    def test_disclosure_arrow_and_accessible_state_track_each_toggle(self) -> None:
        toggle = self.panel._toggle_button
        self.assertEqual(toggle.arrowType(), Qt.ArrowType.DownArrow)
        self.assertIn("Expanded", toggle.accessibleName())
        self.assertEqual(toggle.accessibleName(), f"{toggle.text()}, Expanded")
        toggle.click()
        self.assertEqual(toggle.arrowType(), Qt.ArrowType.RightArrow)
        self.assertIn("Collapsed", toggle.accessibleName())
        toggle.click()
        self.assertEqual(toggle.arrowType(), Qt.ArrowType.DownArrow)
        self.assertIn("Expanded", toggle.accessibleName())

    def test_table_tab_leaves_control_and_shift_tab_returns_in_visual_order(self) -> None:
        self.panel.set_attachments([self.attachments[0]])
        self.app.processEvents()
        table = self.panel._table
        self.assertFalse(table.tabKeyNavigation())

        sequence = [
            self.panel._toggle_button,
            self.panel._open_button,
            self.panel._save_button,
            self.panel._save_all_button,
            table,
        ]
        for current, following in zip(sequence, sequence[1:]):
            current.setFocus()
            QTest.keyClick(current, Qt.Key.Key_Tab)
            self.assertIs(self.app.focusWidget(), following)

        QTest.keyClick(table, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
        self.assertIs(self.app.focusWidget(), self.panel._save_all_button)

    def test_unknown_extension_type_escapes_bidi_controls_and_empty_escape_bubbles(self) -> None:
        attachment = AttachmentInfo(90, "report.\u202edoc", "application/msword", 1)
        self.panel.set_attachments([attachment])
        self.assertIn("\\u202e", self.panel._table.item(0, 1).text())

        table = self.panel._table
        table.clearSelection()
        from PySide6.QtGui import QKeyEvent
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        event.setAccepted(False)
        table.keyPressEvent(event)
        self.assertFalse(event.isAccepted())

    def test_context_keyboard_dispatches_without_clipboard_side_effect(self) -> None:
        table = self.panel._table
        table.setCurrentCell(1, 0)
        seen = []
        self.panel._show_context_menu = lambda point: seen.append(point)
        table.setFocus()
        QTest.keyClick(table, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(len(seen), 1)
        self.assertGreaterEqual(seen[0].x(), 0)

    def test_context_targeting_replaces_unselected_rows(self) -> None:
        self.panel._select_context_row(0)
        self.panel._select_context_row(2)
        self.assertEqual(self.panel.selected_attachments(), [self.attachments[2]])

    def test_clear_hides_panel_and_preserves_instance_expansion_choice(self) -> None:
        self.panel._toggle_button.click()
        self.panel.clear()
        self.assertTrue(self.panel.isHidden())
        self.panel.set_attachments(self.attachments)
        self.assertTrue(self.panel._table.isHidden())

    def test_retranslate_refreshes_types_and_preserves_selection_and_collapse(self) -> None:
        attachments = [
            AttachmentInfo(50, "image.png", "application/pdf", 1),
            AttachmentInfo(60, "notes.txt", "text/plain", 2),
        ]
        self.panel.set_attachments(attachments)
        self.panel._select_context_row(0)
        self.panel._toggle_button.click()
        self.assertEqual(self.panel._table.item(0, 1).text(), "Image")
        self.assertIn("Declared content type differs", self.panel._table.item(0, 1).toolTip())

        set_language("ko")
        self.panel.retranslate_ui()

        self.assertEqual(self.panel.selected_attachments(), [attachments[0]])
        self.assertTrue(self.panel._table.isHidden())
        self.assertFalse(self.panel._expanded)
        self.assertEqual(self.panel._table.item(0, 1).text(), "이미지")
        self.assertIn("콘텐츠 유형과", self.panel._table.item(0, 1).toolTip())
        self.assertIn("첨부파일", self.panel._table.accessibleName())

    def test_hint_uses_eliding_label_and_card_uses_styled_background(self) -> None:
        self.assertTrue(self.panel.testAttribute(Qt.WidgetAttribute.WA_StyledBackground))
        self.assertTrue(hasattr(self.panel._hint_label, "fullText"))


if __name__ == "__main__":
    unittest.main()
