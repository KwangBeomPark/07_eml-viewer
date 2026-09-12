from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from eml_viewer.gui.i18n import set_language
from eml_viewer.gui.theme import apply_theme
from eml_viewer.models.app_settings import AppSettings
from eml_viewer.services.attachment_service import AttachmentService
from eml_viewer.services.eml_parser import EmlParser
from eml_viewer.services.file_operation_service import FileOperationService
from eml_viewer.services.forward_service import ForwardService
from eml_viewer.services.settings_service import SettingsService
from eml_viewer.services.update_service import UpdateService

if TYPE_CHECKING:
    from eml_viewer.gui.main_window import MainWindow

logger = logging.getLogger(__name__)


class WindowManager(QObject):
    """애플리케이션 내의 모든 MainWindow 인스턴스를 관리하고 다중 창 및 상태 동기화를 담당합니다."""

    def __init__(
        self,
        parser: EmlParser | None = None,
        settings_service: SettingsService | None = None,
        file_operation_service: FileOperationService | None = None,
        attachment_service: AttachmentService | None = None,
        forward_service: ForwardService | None = None,
        update_service: UpdateService | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._parser = parser or EmlParser()
        self._settings_service = settings_service or SettingsService()
        self._file_operation_service = file_operation_service or FileOperationService()
        self._attachment_service = attachment_service or AttachmentService(
            self._parser, self._file_operation_service
        )
        self._forward_service = forward_service or ForwardService()
        self._update_service = update_service or UpdateService()

        self._windows: list[MainWindow] = []
        self._update_checked: bool = False

    @property
    def windows(self) -> list[MainWindow]:
        return list(self._windows)

    def create_window(self, file_path: str | Path | None = None) -> MainWindow:
        from eml_viewer.gui.main_window import MainWindow

        # 첫 번째 창에서만 백그라운드 업데이트 확인을 시작하도록 제어
        run_update_check = not self._update_checked
        if run_update_check:
            self._update_checked = True

        window = MainWindow(
            parser=self._parser,
            attachment_service=self._attachment_service,
            settings_service=self._settings_service,
            file_operation_service=self._file_operation_service,
            forward_service=self._forward_service,
            update_service=self._update_service,
            window_manager=self,
            auto_check_update=run_update_check,
        )

        app = QApplication.instance()
        if app is not None and not app.windowIcon().isNull():
            window.setWindowIcon(app.windowIcon())

        # 이전 창이 열려있으면 위치를 살짝 오프셋하여 겹치지 않게 표시하되, 화면 밖으로 벗어나지 않도록 클램프
        if self._windows:
            last_win = self._windows[-1]
            pos = last_win.pos()
            screen = QApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                new_x = pos.x() + 30
                new_y = pos.y() + 30
                if new_x + 200 > avail.right() or new_y + 200 > avail.bottom():
                    new_x, new_y = avail.x() + 40, avail.y() + 40
                window.move(new_x, new_y)
            else:
                window.move(pos.x() + 30, pos.y() + 30)

        self._windows.append(window)
        window.show()

        if file_path is not None:
            path_obj = Path(file_path)
            if path_obj.exists() and path_obj.is_file():
                window.load_email(path_obj)

        return window

    def unregister_window(self, window: MainWindow) -> None:
        if window in self._windows:
            self._windows.remove(window)
            logger.info("Window unregistered. Remaining open windows: %d", len(self._windows))

        if not self._windows:
            app = QApplication.instance()
            if app is not None:
                app.quit()

    def broadcast_settings(self, new_settings: AppSettings) -> None:
        """설정(언어, 테마, 이미지 로드 옵션 등)을 저장하고 열려 있는 모든 창에 실시간 반영합니다."""
        self._settings_service.save_settings(new_settings)
        set_language(new_settings.language)

        app = QApplication.instance()
        if app is not None:
            apply_theme(app, new_settings.theme)

        for win in self._windows:
            try:
                win.apply_settings(new_settings)
            except Exception as exc:
                logger.warning("Failed to broadcast settings to window: %s", exc)
