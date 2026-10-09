from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_folder_navigation(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        with tempfile.TemporaryDirectory() as temp_dir:
            dir_path = Path(temp_dir)
            f1 = dir_path / "email1.eml"
            f2 = dir_path / "email2.eml"
            f3 = dir_path / "email3.eml"
            for f in (f1, f2, f3):
                f.write_text("Subject: Test\n\nBody", encoding="utf-8")

            window.load_email(f2)
            self.assertEqual(window._current_folder_index, 1)
            self.assertTrue(window._prev_email_action.isEnabled())
            self.assertTrue(window._next_email_action.isEnabled())

            # 이전 이메일로 이동
            window._prev_email_action.trigger()
            self.assertEqual(window._current_folder_index, 0)
            self.assertFalse(window._prev_email_action.isEnabled())
            self.assertTrue(window._next_email_action.isEnabled())

            # 다음 이메일로 이동 (f1 -> f2)
            window._next_email_action.trigger()
            self.assertEqual(window._current_folder_index, 1)

            # 다음 이메일로 이동 (f2 -> f3)
            window._next_email_action.trigger()
            self.assertEqual(window._current_folder_index, 2)
            self.assertTrue(window._prev_email_action.isEnabled())
            self.assertFalse(window._next_email_action.isEnabled())

    def test_recent_files_menu_updated_on_load(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "recent_test.eml"
            file_path.write_text("Subject: Recent\n\nBody", encoding="utf-8")

            window.load_email(file_path)
            actions = window._recent_files_menu.actions()
            # 1 file entry + 1 separator + 1 clear action = 3
            file_actions = [a for a in actions if not a.isSeparator() and a.isEnabled()]
            self.assertEqual(len(file_actions), 2)  # file entry + clear
            self.assertIn("recent_test.eml", file_actions[0].text())

    def test_view_source_dialog(self) -> None:
        from unittest.mock import patch
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        window._display_email(
            ParsedEmail(
                subject="Source Test",
                sender="sender@example.com",
                recipients="receiver@example.com",
                date="2026-06-27",
                plain_body="Source Plain Body",
                html_body="",
                raw_headers="Subject: Source Test\nFrom: sender@example.com",
            )
        )

        with patch("eml_viewer.gui.dialogs.show_source_dialog") as mock_source_dialog:
            window._view_source_action.trigger()
            mock_source_dialog.assert_called_once()
            args = mock_source_dialog.call_args[0]
            self.assertNotEqual(args[1], "dialog.source.title")
            self.assertEqual(args[1], "Message Source")
            self.assertIn("Source Test", args[2])
            self.assertIn("Source Plain Body", args[2])

    def test_recent_files_menu_shows_empty_when_no_files(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        actions = window._recent_files_menu.actions()
        self.assertEqual(len(actions), 1)
        self.assertFalse(actions[0].isEnabled())
        self.assertEqual(actions[0].text(), "(No Recent Files)")

    def test_settings_save_failure_does_not_apply_changes_or_claim_success(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        dialog = MagicMock()
        dialog.exec.return_value = 1
        dialog.language = "en"
        dialog.theme = "dark"
        dialog.auto_load_remote_images = True
        dialog.smtp_host = "smtp.example.com"
        dialog.smtp_sender = "sender@example.com"
        dialog.smtp_port = 587
        with patch("eml_viewer.gui.main_window.SettingsDialog", return_value=dialog) as dialog_class, patch.object(
            window._settings_service, "save_settings", side_effect=PermissionError("locked"),
        ), patch.object(window, "apply_settings") as apply_settings, patch(
            "eml_viewer.gui.dialogs.show_error",
        ) as show_error, patch("eml_viewer.gui.dialogs.show_info") as show_info:
            dialog_class.DialogCode.Accepted = 1
            window._open_settings()
        apply_settings.assert_not_called()
        show_error.assert_called_once()
        show_info.assert_not_called()
        self.assertIn("Could not save", window.statusBar().currentMessage())

    def test_settings_broadcast_failure_is_reported(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        manager = MagicMock()
        manager.broadcast_settings.side_effect = PermissionError("locked")
        window._window_manager = manager
        dialog = MagicMock()
        dialog.exec.return_value = 1
        with patch("eml_viewer.gui.main_window.SettingsDialog", return_value=dialog) as dialog_class, patch(
            "eml_viewer.gui.dialogs.show_error",
        ) as show_error:
            dialog_class.DialogCode.Accepted = 1
            window._open_settings()
        manager.broadcast_settings.assert_called_once()
        show_error.assert_called_once()
        self.assertIn("Could not save", window.statusBar().currentMessage())

    def test_settings_startup_sync_failure_shows_warning(self) -> None:
        from dataclasses import replace
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        current = window._settings_service.load_settings()
        manager = MagicMock()
        # 사용자는 True로 변경하려 했으나 실제로는 False로 되돌아옴
        manager.broadcast_settings.return_value = replace(current, startup_with_windows=False)
        window._window_manager = manager
        dialog = MagicMock()
        dialog.exec.return_value = 1
        dialog.startup_with_windows = True
        dialog.language = current.language
        dialog.theme = current.theme
        dialog.auto_load_remote_images = current.auto_load_remote_images
        dialog.minimize_to_tray_on_close = current.minimize_to_tray_on_close
        dialog.smtp_host = current.smtp_host
        dialog.smtp_sender = current.smtp_sender
        dialog.smtp_port = current.smtp_port
        with patch("eml_viewer.gui.main_window.SettingsDialog", return_value=dialog) as dialog_class, patch(
            "eml_viewer.gui.dialogs.show_warning",
        ) as show_warning:
            dialog_class.DialogCode.Accepted = 1
            window._open_settings()
        show_warning.assert_called_once()

    def test_recent_history_failure_does_not_interrupt_email_navigation(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "mail.eml"
            file_path.write_text("Subject: Test\n\nBody", encoding="utf-8")
            with patch.object(window._settings_service, "add_recent_file", side_effect=OSError("disk full")), patch(
                "eml_viewer.gui.dialogs.show_error",
            ) as show_error:
                window.load_email(file_path)
            self.assertEqual(window._current_email.subject, "Test")
            self.assertEqual(window._current_folder_index, 0)
            show_error.assert_called_once()

    def test_clear_recent_failure_keeps_saved_history(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "mail.eml"
            file_path.write_text("Subject: Test\n\nBody", encoding="utf-8")
            window.load_email(file_path)
            original = window._settings_service.settings_path.read_bytes()
            with patch.object(window._settings_service, "save_settings", side_effect=PermissionError("locked")), patch(
                "eml_viewer.gui.dialogs.show_error",
            ) as show_error:
                window._clear_recent_files()
            self.assertEqual(window._settings_service.settings_path.read_bytes(), original)
            self.assertIn("mail.eml", window._recent_files_menu.actions()[0].text())
            self.assertIn("Could not save", window.statusBar().currentMessage())
            show_error.assert_called_once()

    def test_export_pdf_triggers_callback_and_shows_success(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        window._display_email(
            ParsedEmail(
                subject="PDF Export Test",
                sender="sender@example.com",
                recipients="receiver@example.com",
                date="2026-06-27",
                plain_body="PDF Content",
                html_body="",
            )
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            out_file = str(Path(temp_dir) / "test_out.pdf")
            with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=(out_file, "PDF (*.pdf)")), \
                 patch("eml_viewer.gui.dialogs.show_info") as mock_info:
                window._export_pdf_action.trigger()
                mock_info.assert_called_once()
                self.assertIn("test_out.pdf", mock_info.call_args[0][2])

    def test_recipient_history_failure_does_not_mark_sent_mail_as_failed(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        window._current_email = ParsedEmail(
            subject="Sent mail", sender="sender@example.com", recipients="recipient@example.com",
            date="2026-10-07", plain_body="Body", html_body="",
        )
        selection = dialogs.ForwardRecipientSelection("recipient@example.com", ())
        with patch("eml_viewer.gui.dialogs.request_forward_recipients", return_value=selection), patch.object(
            window._forward_service, "forward_email", return_value="recipient@example.com",
        ) as forward, patch.object(
            window._settings_service, "save_recent_recipients", side_effect=OSError("disk full"),
        ), patch("eml_viewer.gui.dialogs.show_error") as show_error, patch(
            "eml_viewer.gui.dialogs.show_info",
        ) as show_info:
            window._forward_current_email()
        forward.assert_called_once()
        show_error.assert_called_once()
        show_info.assert_called_once()
        self.assertIn("recipient@example.com", show_info.call_args[0][2])

    def test_quit_action_calls_force_quit_on_window_manager(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        mock_manager = MagicMock()
        window._window_manager = mock_manager
        window._quit_action.trigger()
        mock_manager.force_quit.assert_called_once()

    def test_exit_action_closes_current_window(self) -> None:
        window = self._window(UpdateCheckResult("0.1.4", "0.1.4", "https://example.com", None))
        mock_manager = MagicMock()
        window._window_manager = mock_manager
        closed = []
        original_close_event = window.closeEvent

        def custom_close_event(event):
            closed.append(True)
            original_close_event(event)

        window.closeEvent = custom_close_event
        window._exit_action.trigger()
        self.assertTrue(closed)
        mock_manager.force_quit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
