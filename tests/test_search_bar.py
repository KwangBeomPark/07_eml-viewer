from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from eml_viewer.gui.message_widgets import MessageBodyWidget
from eml_viewer.gui.search_bar import SearchBarWidget
from eml_viewer.models.email_data import ParsedEmail


class SearchBarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_search_bar_signals_and_matching(self) -> None:
        widget = MessageBodyWidget()
        email = ParsedEmail(
            subject="Search Test",
            sender="sender@example.com",
            recipients="to@example.com",
            date="2026-06-27",
            plain_body="Apple Banana Apple Cherry Apple",
            html_body="",
            source_path=Path("test.eml"),
        )
        widget.set_email(email)

        # 검색 바 열기
        widget.show_search_bar()
        self.assertFalse(widget._search_bar.isHidden())

        # 'Apple' 검색
        widget._search_bar._search_input.setText("Apple")
        self.assertEqual(len(widget._search_matches), 3)
        self.assertEqual(widget._current_match_index, 0)
        self.assertEqual(widget._search_bar._count_label.text(), "1 / 3")
        self.assertEqual(len(widget._plain_browser.extraSelections()), 3)

        # 다음 검색 (F3 또는 _next_button)
        widget.find_next()
        self.assertEqual(widget._current_match_index, 1)
        self.assertEqual(widget._search_bar._count_label.text(), "2 / 3")

        widget.find_next()
        self.assertEqual(widget._current_match_index, 2)
        self.assertEqual(widget._search_bar._count_label.text(), "3 / 3")

        # 순환 다음 검색 -> 0번으로
        widget.find_next()
        self.assertEqual(widget._current_match_index, 0)
        self.assertEqual(widget._search_bar._count_label.text(), "1 / 3")

        # 이전 검색 (Shift+F3)
        widget.find_previous()
        self.assertEqual(widget._current_match_index, 2)
        self.assertEqual(widget._search_bar._count_label.text(), "3 / 3")

        # 검색 바 닫기 -> 하이라이트 지워짐
        widget._search_bar.close_search()
        self.assertTrue(widget._search_bar.isHidden())
        self.assertEqual(len(widget._plain_browser.extraSelections()), 0)
        self.assertEqual(len(widget._search_matches), 0)

    def test_search_no_matches(self) -> None:
        widget = MessageBodyWidget()
        email = ParsedEmail(
            subject="Search Test",
            sender="sender@example.com",
            recipients="to@example.com",
            date="2026-06-27",
            plain_body="Hello World",
            html_body="",
            source_path=Path("test.eml"),
        )
        widget.set_email(email)

        widget.show_search_bar()
        widget._search_bar._search_input.setText("NotExistKeyword")
        self.assertEqual(len(widget._search_matches), 0)
        self.assertEqual(len(widget._plain_browser.extraSelections()), 0)
        self.assertIn("일치 항목 없음", widget._search_bar._count_label.text())

    def test_set_email_refreshes_search_state(self) -> None:
        widget = MessageBodyWidget()
        email1 = ParsedEmail(
            subject="Email 1",
            sender="sender@example.com",
            recipients="to@example.com",
            date="2026-06-27",
            plain_body="Hello Apple",
            html_body="",
            source_path=Path("test1.eml"),
        )
        widget.set_email(email1)
        widget.show_search_bar()
        widget._search_bar._search_input.setText("Apple")
        self.assertEqual(len(widget._search_matches), 1)

        # 새 이메일 로드 (Apple이 2개 포함)
        email2 = ParsedEmail(
            subject="Email 2",
            sender="sender@example.com",
            recipients="to@example.com",
            date="2026-06-27",
            plain_body="Apple and another Apple",
            html_body="",
            source_path=Path("test2.eml"),
        )
        widget.set_email(email2)
        # 검색바가 열려있으므로 새 메일에 대해 자동으로 재검색 실행됨
        self.assertEqual(len(widget._search_matches), 2)
        self.assertEqual(widget._search_bar._count_label.text(), "1 / 2")


if __name__ == "__main__":
    unittest.main()
