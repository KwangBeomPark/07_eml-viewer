from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt
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

    def tearDown(self) -> None:
        set_language("ko")

    def test_panel_hides_when_no_attachments(self) -> None:
        panel = AttachmentPanel()

        panel.set_attachments([])

        self.assertTrue(panel.isHidden())
        self.assertTrue(panel._table.isHidden())

    def test_panel_defaults_to_expanded_when_attachments_exist(self) -> None:
        panel = AttachmentPanel()
        attachments = [
            AttachmentInfo(index=1, filename="a.txt", content_type="text/plain", size=1024),
            AttachmentInfo(index=2, filename="b.pdf", content_type="application/pdf", size=2048),
        ]

        panel.set_attachments(attachments)

        self.assertFalse(panel.isHidden())
        self.assertFalse(panel._table.isHidden())
        self.assertEqual(panel._toggle_button.text(), "Collapse")
        self.assertEqual(panel._title_label.text(), "Attachments 2 · 3.0 KB · Selected 0")
        self.assertGreater(panel.maximumHeight(), 48)

    def test_toggle_collapses_and_expands_list(self) -> None:
        panel = AttachmentPanel()
        attachments = [
            AttachmentInfo(index=index, filename=f"{index}.txt", content_type="text/plain", size=1)
            for index in range(1, 10)
        ]

        panel.set_attachments(attachments)
        expanded_height = panel.maximumHeight()

        # 기본 펼침 상태에서 토글 클릭 -> 접힘
        panel._toggle_button.click()
        self.assertTrue(panel._table.isHidden())
        self.assertEqual(panel._toggle_button.text(), "Expand")
        self.assertLessEqual(panel.maximumHeight(), 48)

        # 다시 클릭 -> 펼침
        panel._toggle_button.click()
        self.assertFalse(panel._table.isHidden())
        self.assertEqual(panel._toggle_button.text(), "Collapse")
        self.assertEqual(panel.maximumHeight(), expanded_height)

    def test_checked_rows_drive_selection_and_button_states(self) -> None:
        panel = AttachmentPanel()
        attachments = [
            AttachmentInfo(index=1, filename="a.txt", content_type="text/plain", size=1),
            AttachmentInfo(index=2, filename="b.txt", content_type="text/plain", size=1),
        ]

        panel.set_attachments(attachments)
        self.assertFalse(panel._save_button.isEnabled())
        self.assertFalse(panel._open_button.isEnabled())

        panel._table.item(0, 0).setCheckState(Qt.CheckState.Checked)

        self.assertEqual(panel.selected_attachments(), [attachments[0]])
        self.assertTrue(panel._save_button.isEnabled())
        self.assertTrue(panel._open_button.isEnabled())
        self.assertEqual(panel._title_label.text(), "Attachments 2 · 2 B · Selected 1")

    def test_open_button_and_double_click_emit_open_requested(self) -> None:
        panel = AttachmentPanel()
        attachments = [
            AttachmentInfo(index=1, filename="a.txt", content_type="text/plain", size=1),
        ]
        panel.set_attachments(attachments)

        received = []
        panel.open_requested.connect(received.append)

        # 1) 체크 후 열기 버튼 클릭
        panel._table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        panel._open_button.click()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0], [attachments[0]])

        # 2) 체크박스 열(0번) 더블클릭은 무시되어야 함
        panel._table.cellDoubleClicked.emit(0, 0)
        self.assertEqual(len(received), 1)

        # 3) 파일명 열(1번) 셀 더블클릭 -> 열기 발생
        panel._table.cellDoubleClicked.emit(0, 1)
        self.assertEqual(len(received), 2)
        self.assertEqual(received[1], [attachments[0]])


if __name__ == "__main__":
    unittest.main()
