from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from eml_viewer.gui.tray_manager import TrayManager
from eml_viewer.models.app_settings import AppSettings

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_tray_manager_initialization():
    app = QApplication.instance() or QApplication([])
    mock_window_manager = MagicMock()
    mock_startup_manager = MagicMock()
    mock_startup_manager.is_startup_enabled.return_value = False
    mock_settings_service = MagicMock()
    mock_settings_service.load_settings.return_value = AppSettings()

    tray = TrayManager(
        window_manager=mock_window_manager,
        startup_manager=mock_startup_manager,
        settings_service=mock_settings_service,
        icon=QIcon(),
    )

    if QSystemTrayIcon.isSystemTrayAvailable():
        assert tray.is_available
        tray.show()
        tray.hide()

        # 새 창 열기 액션 테스트
        tray._on_open_new_window()
        mock_window_manager.create_window.assert_called_once()

        # 시작프로그램 토글 테스트
        tray._on_toggle_startup(True)
        mock_startup_manager.set_startup_enabled.assert_called_with(True)

        # 액션 상태 갱신 테스트
        mock_startup_manager.is_startup_enabled.return_value = True
        tray.update_action_states()

        # 종료 액션 테스트
        tray._on_exit()
        mock_window_manager.force_quit.assert_called_once()


def test_tray_manager_unavailable_when_icon_is_null(monkeypatch):
    """아이콘이 완전히 null인 환경에서는 백그라운드 좀비 프로세스를 방지하기 위해 is_available이 False여야 함."""
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    # app.windowIcon과 app.style() fallback을 무효화하여 icon.isNull() 상태 시뮬레이션
    monkeypatch.setattr(app, "windowIcon", lambda: QIcon())
    monkeypatch.setattr(app, "style", lambda: None)

    tray = TrayManager(
        window_manager=MagicMock(),
        startup_manager=MagicMock(),
        settings_service=MagicMock(),
        icon=QIcon(),
    )
    assert not tray.is_available
