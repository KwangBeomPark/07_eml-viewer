from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication

from eml_viewer.gui.window_manager import WindowManager
from eml_viewer.models.app_settings import AppSettings
from eml_viewer.services.attachment_service import AttachmentService
from eml_viewer.services.eml_parser import EmlParser
from eml_viewer.services.file_operation_service import FileOperationService
from eml_viewer.services.forward_service import ForwardService
from eml_viewer.services.settings_service import SettingsService
from eml_viewer.services.startup_manager import StartupManager
from eml_viewer.services.update_service import UpdateService


class WindowManagerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.mock_startup_dir = Path(self.temp_dir.name) / "Startup"
        self.mock_startup_dir.mkdir(parents=True, exist_ok=True)
        self.startup_manager = StartupManager(startup_dir=self.mock_startup_dir)

        self.parser = EmlParser()
        self.file_ops = FileOperationService()
        self.settings_service = SettingsService(Path(self.temp_dir.name) / "settings.json")
        self.attachment_service = AttachmentService(self.parser, self.file_ops)
        self.update_service = MagicMock(spec=UpdateService)

        self.manager = WindowManager(
            parser=self.parser,
            settings_service=self.settings_service,
            file_operation_service=self.file_ops,
            attachment_service=self.attachment_service,
            forward_service=MagicMock(spec=ForwardService),
            update_service=self.update_service,
            startup_manager=self.startup_manager,
        )

    def tearDown(self) -> None:
        for win in list(self.manager.windows):
            win.close()
        self.app.processEvents()

    def test_create_and_unregister_window(self) -> None:
        self.assertEqual(len(self.manager.windows), 0)

        # 첫 번째 창 생성
        win1 = self.manager.create_window()
        self.assertEqual(len(self.manager.windows), 1)
        self.assertIn(win1, self.manager.windows)
        self.assertTrue(win1.isVisible())

        # 두 번째 창 생성
        win2 = self.manager.create_window()
        self.assertEqual(len(self.manager.windows), 2)
        self.assertIn(win2, self.manager.windows)

        # 위치 오프셋 검증
        self.assertEqual(win2.x(), win1.x() + 30)
        self.assertEqual(win2.y(), win1.y() + 30)

        # 닫을 때 등록 해제
        win1.close()
        self.assertEqual(len(self.manager.windows), 1)
        self.assertNotIn(win1, self.manager.windows)
        self.assertIn(win2, self.manager.windows)

        win2.close()
        self.assertEqual(len(self.manager.windows), 0)

    def test_broadcast_settings(self) -> None:
        win1 = self.manager.create_window()
        win2 = self.manager.create_window()

        new_settings = AppSettings(
            language="en",
            theme="dark",
            auto_load_remote_images=True,
        )

        self.manager.broadcast_settings(new_settings)

        # settings 파일 저장 확인
        loaded = self.settings_service.load_settings()
        self.assertEqual(loaded.language, "en")
        self.assertEqual(loaded.theme, "dark")
        self.assertTrue(loaded.auto_load_remote_images)

        # 각 창의 body widget에 설정 반영 확인
        self.assertTrue(win1._body_widget._remote_images_auto_load)
        self.assertTrue(win2._body_widget._remote_images_auto_load)

    def test_failed_save_does_not_broadcast_settings(self) -> None:
        window = MagicMock()
        self.manager._windows.append(window)
        with patch.object(self.settings_service, "save_settings", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                self.manager.broadcast_settings(AppSettings(auto_load_remote_images=True))
        window.apply_settings.assert_not_called()

    def test_failed_save_rolls_back_startup_setting(self) -> None:
        # 기존 시작프로그램 설정이 비활성화(False) 상태인 경우
        self.assertFalse(self.startup_manager.is_startup_enabled())
        with patch.object(self.settings_service, "save_settings", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                self.manager.broadcast_settings(AppSettings(startup_with_windows=True))
        # 저장 실패 후 다시 False로 롤백되어 있어야 함
        self.assertFalse(self.startup_manager.is_startup_enabled())

    def test_tray_keeps_app_alive_when_all_windows_closed(self) -> None:
        mock_tray = MagicMock()
        mock_tray.is_available = True
        self.manager.set_tray_manager(mock_tray)
        self.settings_service.save_settings(AppSettings(minimize_to_tray_on_close=True))

        win = self.manager.create_window()
        self.assertEqual(len(self.manager.windows), 1)

        with patch.object(self.app, "quit") as mock_quit:
            win.close()
            self.assertEqual(len(self.manager.windows), 0)
            mock_quit.assert_not_called()

    def test_handle_ipc_message_creates_or_activates_window(self) -> None:
        win = self.manager.handle_ipc_message("__NEW_WINDOW__")
        self.assertIn(win, self.manager.windows)
        self.assertTrue(win.isVisible())

    def test_force_quit_closes_windows_and_quits_app(self) -> None:
        win = self.manager.create_window()
        mock_tray = MagicMock()
        self.manager.set_tray_manager(mock_tray)

        with patch.object(self.app, "quit") as mock_quit:
            self.manager.force_quit()
            self.assertTrue(self.manager._force_quitting)
            mock_tray.hide.assert_called_once()
            mock_quit.assert_called_once()
        self.app.processEvents()
        self.manager._force_quitting = False

    def test_warmup_webengine_executes_safely(self) -> None:
        # WebEngine warm-up이 예외 없이 안전하게 수행되는지 확인
        self.manager.warmup_webengine()

    def test_broadcast_settings_reverts_startup_on_failure(self) -> None:
        mock_startup = MagicMock()
        mock_startup.set_startup_enabled.return_value = False
        mock_startup.is_startup_enabled.return_value = False
        self.manager.set_startup_manager(mock_startup)

        # 사용자가 startup_with_windows=True로 설정을 변경했으나 등록이 실패한 경우
        self.manager.broadcast_settings(AppSettings(startup_with_windows=True))

        # 실제 상태인 False로 보정되어 저장되었는지 검증
        saved = self.settings_service.load_settings()
        self.assertFalse(saved.startup_with_windows)

    def test_broadcast_settings_syncs_startup_when_target_path_differs(self) -> None:
        """바로가기가 이미 켜져 있어도 대상 경로가 현재 실행 파일과 다르면 바로가기를 갱신하는지 검증합니다."""
        root = Path(self.temp_dir.name)
        target_a = root / "LocationA" / "EmlViewer.exe"
        target_b = root / "LocationB" / "EmlViewer.exe"
        target_a.parent.mkdir(parents=True)
        target_a.touch()
        target_b.parent.mkdir(parents=True)
        target_b.touch()

        # LocationA로 바로가기 생성
        sm_a = StartupManager(startup_dir=root / "Startup", target_path=target_a)
        self.assertTrue(sm_a.enable_startup())
        self.assertEqual(sm_a.get_shortcut_target(), str(target_a.resolve()))

        # LocationB로 실행된 WindowManager에서 broadcast_settings 호출
        sm_b = StartupManager(startup_dir=root / "Startup", target_path=target_b)
        self.manager.set_startup_manager(sm_b)

        # startup_with_windows=True는 이미 켜져 있는 상태지만 대상이 다르므로 갱신되어야 함
        self.manager.broadcast_settings(AppSettings(startup_with_windows=True))
        self.assertEqual(sm_b.get_shortcut_target(), str(target_b.resolve()))
        self.assertTrue(sm_b.is_target_current())

    def test_broadcast_settings_repairs_damaged_startup_shortcut(self) -> None:
        """손상된 바로가기 파일이 존재하는 경우 broadcast_settings가 이를 정상 바로가기로 수리하는지 검증합니다."""
        root = Path(self.temp_dir.name)
        target = root / "App" / "EmlViewer.exe"
        target.parent.mkdir(parents=True)
        target.touch()

        sm = StartupManager(startup_dir=root / "Startup", target_path=target)
        sm.get_startup_dir().mkdir(parents=True, exist_ok=True)
        sm.get_shortcut_path().write_bytes(b"corrupted shortcut content")

        self.assertTrue(sm.is_startup_enabled())
        self.assertFalse(sm.is_target_current())

        self.manager.set_startup_manager(sm)
        saved = self.manager.broadcast_settings(AppSettings(startup_with_windows=True))

        self.assertTrue(saved.startup_with_windows)
        self.assertTrue(sm.is_target_current())
        self.assertEqual(sm.get_shortcut_target(), str(target.resolve()))

    def test_unregister_window_defers_delete_during_active_print(self) -> None:
        """비동기 인쇄 작업이 진행 중일 때 창 닫기 시 deleteLater가 인쇄 완료 시점까지 보류되는지 검증합니다."""
        win = self.manager.create_window()
        mock_body = MagicMock()
        mock_body._active_printer = object()
        mock_html = MagicMock()
        mock_body._html_view = mock_html
        win._body_widget = mock_body

        with patch.object(win, "deleteLater") as mock_delete:
            self.manager.unregister_window(win)
            # 인쇄 중이므로 즉시 삭제되지 않고 pending_print_windows에 보관되어야 함
            mock_delete.assert_not_called()
            self.assertIn(win, self.manager._pending_print_windows)

            # printFinished 시그널 방출 시뮬레이션
            print_finish_callback = mock_html.printFinished.connect.call_args[0][0]
            print_finish_callback(True)

            # 인쇄 완료 후 deleteLater 호출 및 목록에서 제거되어야 함
            mock_delete.assert_called_once()
            self.assertNotIn(win, self.manager._pending_print_windows)


if __name__ == "__main__":
    unittest.main()
