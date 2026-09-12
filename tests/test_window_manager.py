from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

from eml_viewer.gui.window_manager import WindowManager
from eml_viewer.models.app_settings import AppSettings
from eml_viewer.services.attachment_service import AttachmentService
from eml_viewer.services.eml_parser import EmlParser
from eml_viewer.services.file_operation_service import FileOperationService
from eml_viewer.services.forward_service import ForwardService
from eml_viewer.services.settings_service import SettingsService
from eml_viewer.services.update_service import UpdateService


class WindowManagerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

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
        )

    def tearDown(self) -> None:
        for win in list(self.manager.windows):
            win.close()

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


if __name__ == "__main__":
    unittest.main()
