from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-software-rasterizer --no-sandbox")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication

from eml_viewer.gui import dialogs
from eml_viewer.gui.i18n import set_language
from eml_viewer.gui.main_window import MainWindow
from eml_viewer.models.app_settings import AppSettings
from eml_viewer.models.email_data import ParsedEmail
from eml_viewer.services.attachment_service import AttachmentService
from eml_viewer.services.eml_parser import EmlParser
from eml_viewer.services.file_operation_service import FileOperationService
from eml_viewer.services.settings_service import SettingsService
from eml_viewer.services.update_service import UpdateCheckResult


class FakeUpdateService:
    def __init__(self, result: UpdateCheckResult) -> None:
        self._result = result

    def check_for_updates(self) -> UpdateCheckResult:
        return self._result


class MainWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        set_language("en")

    def tearDown(self) -> None:
        set_language("ko")

    def _window(
        self,
        update_result: UpdateCheckResult,
        app_settings: AppSettings | None = None,
    ) -> MainWindow:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        parser = EmlParser()
        file_operations = FileOperationService()
        settings = SettingsService(Path(temp_dir.name) / "settings.json")
        if app_settings is not None:
            settings.save_settings(app_settings)
        window = MainWindow(
            parser=parser,
            attachment_service=AttachmentService(parser, file_operations),
            settings_service=settings,
            file_operation_service=file_operations,
            update_service=FakeUpdateService(update_result),
        )
        self.addCleanup(window.close)
        if window._update_check_thread is not None:
            window._update_check_thread.wait(5000)
            QApplication.processEvents()
        return window

    def test_offscreen_saved_geometry_is_centered_on_primary_screen(self) -> None:
        window = self._window(
            UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None),
            app_settings=AppSettings(
                window_x=10_000,
                window_y=10_000,
                window_width=800,
                window_height=600,
            ),
        )

        primary_screen = QApplication.primaryScreen()
        self.assertIsNotNone(primary_screen)
        available_geometry = primary_screen.availableGeometry()
        geometry = window.geometry()

        self.assertTrue(available_geometry.contains(geometry.center()))
        self.assertLessEqual(geometry.width(), available_geometry.width())
        self.assertLessEqual(geometry.height(), available_geometry.height())

    def test_visible_saved_geometry_is_preserved(self) -> None:
        window = self._window(
            UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None),
            app_settings=AppSettings(
                window_x=50,
                window_y=50,
                window_width=500,
                window_height=400,
            ),
        )

        self.assertEqual(window.geometry().getRect(), (50, 50, 500, 400))

    def test_update_banner_shows_only_when_update_is_available(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.5", "https://example.com", None))

        self.assertFalse(window._update_banner.isHidden())
        self.assertIn("0.1.5", window._update_banner_label.text())

    def test_update_banner_stays_hidden_when_current_version_is_latest(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))

        self.assertTrue(window._update_banner.isHidden())

    def test_forward_button_enables_after_email_with_source_path_is_displayed(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        self.assertFalse(window._forward_button.isEnabled())

        email = ParsedEmail(
            subject="Hello",
            sender="sender@example.com",
            recipients="receiver@example.com",
            date="2026-06-27",
            plain_body="Body",
            html_body="",
            source_path=Path("sample.eml"),
        )

        window._display_email(email)

        self.assertTrue(window._forward_button.isEnabled())

    def test_english_language_updates_main_labels_and_menus(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))

        self.assertEqual(window._file_menu.title(), "File")
        self.assertEqual(window._help_menu.title(), "Help")
        self.assertEqual(window._open_button.text(), "Open EML/MSG file")
        self.assertEqual(window._subject_label.text(), "Subject")
        self.assertEqual(window._sender_label.text(), "Sender")
        self.assertEqual(window._to_label.text(), "To")
        self.assertEqual(window._cc_label.text(), "Cc")
        self.assertEqual(window._metadata_group.title(), "Email information")
        self.assertEqual(window._open_browser_action.text(), "Open in Browser")
        self.assertEqual(window._body_widget._open_browser_button.text(), "Open in Browser")

    def test_subject_to_and_cc_copy_buttons_write_to_clipboard(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        window._display_email(
            ParsedEmail(
                subject="Hello",
                sender="sender@example.com",
                recipients="receiver@example.com",
                date="2026-06-27",
                plain_body="Body",
                html_body="",
                source_path=Path("sample.eml"),
                cc="copy@example.com",
            )
        )

        clipboard = QApplication.clipboard()
        self.assertIsNotNone(clipboard)

        window._subject_edit._copy_button.click()
        self.assertEqual(clipboard.text(), "Hello")

        window._to_edit._copy_button.click()
        self.assertEqual(clipboard.text(), "receiver@example.com")

        window._cc_edit._copy_button.click()
        self.assertEqual(clipboard.text(), "copy@example.com")

    def test_open_browser_button_and_action_create_preview_file(self) -> None:
        from unittest.mock import patch

        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        self.assertFalse(window._body_widget._open_browser_button.isEnabled())

        window._display_email(
            ParsedEmail(
                subject="Hello Browser",
                sender="sender@example.com",
                recipients="receiver@example.com",
                date="2026-06-27",
                plain_body="Plain Content",
                html_body="<html><body><h1>Hello HTML</h1></body></html>",
                source_path=Path("sample.eml"),
            )
        )

        self.assertTrue(window._body_widget._open_browser_button.isEnabled())

        preview_file = window._session_temp_dir / "preview.html"
        self.assertFalse(preview_file.exists())

        with patch("os.startfile", create=True) as mock_startfile:
            # 1. Test button click triggers open in browser
            window._body_widget._open_browser_button.click()
            self.assertTrue(preview_file.exists())
            self.assertEqual(mock_startfile.call_count, 1)

            # 2. Test action shortcut/trigger
            window._open_browser_action.trigger()
            self.assertEqual(mock_startfile.call_count, 2)

        content = preview_file.read_text(encoding="utf-8")
        self.assertIn("Hello HTML", content)

    def test_new_window_and_find_actions(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        mock_wm = unittest.mock.MagicMock()
        window._window_manager = mock_wm

        # 1. New Window Action
        window._new_window_action.trigger()
        mock_wm.create_window.assert_called_once()

        # 2. Find Action
        self.assertTrue(window._body_widget._search_bar.isHidden())
        window._find_action.trigger()
        self.assertFalse(window._body_widget._search_bar.isHidden())

    def test_print_action_handles_no_email_or_cancel(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        # 이메일 로드 안 된 상태에서는 아무 작업도 하지 않음
        window._print_action.trigger()

    def test_print_action_delegates_to_body_widget(self) -> None:
        from unittest.mock import patch, MagicMock

        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        window._display_email(
            ParsedEmail(
                subject="Print Test",
                sender="sender@example.com",
                recipients="receiver@example.com",
                date="2026-06-27",
                plain_body="Hello Print Plain",
                html_body="<html><body>Hello Print HTML</body></html>",
                source_path=Path("sample.eml"),
            )
        )

        with patch("PySide6.QtPrintSupport.QPrintDialog") as mock_dialog_cls, \
             patch("PySide6.QtPrintSupport.QPrinter"), \
             patch.object(window._body_widget, "print_content") as mock_print_content:
            mock_dialog = MagicMock()
            mock_dialog.exec.return_value = 1
            mock_dialog_cls.return_value = mock_dialog
            mock_dialog_cls.DialogCode = MagicMock()
            mock_dialog_cls.DialogCode.Accepted = 1

            window._print_action.trigger()
            mock_print_content.assert_called_once()


if __name__ == "__main__":
    unittest.main()

