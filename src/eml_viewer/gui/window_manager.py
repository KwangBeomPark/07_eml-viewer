from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication

from eml_viewer.gui.i18n import set_language
from eml_viewer.gui.theme import apply_theme
from eml_viewer.models.app_settings import AppSettings
from eml_viewer.services.attachment_service import AttachmentService
from eml_viewer.services.eml_parser import EmlParser
from eml_viewer.services.file_operation_service import FileOperationService
from eml_viewer.services.forward_service import ForwardService
from eml_viewer.services.settings_service import SettingsService
from eml_viewer.services.startup_manager import StartupManager
from eml_viewer.services.update_service import UpdateService

if TYPE_CHECKING:
    from eml_viewer.gui.main_window import MainWindow
    from eml_viewer.gui.tray_manager import TrayManager

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
        startup_manager: StartupManager | None = None,
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
        self._startup_manager = startup_manager or StartupManager()

        self._windows: list[MainWindow] = []
        self._update_checked: bool = False
        self._tray_manager: TrayManager | None = None
        self._force_quitting: bool = False
        self._warmup_view: object | None = None
        self._retained_threads: set[object] = set()
        self._pending_print_windows: set[MainWindow] = set()

    @property
    def windows(self) -> list[MainWindow]:
        return list(self._windows)

    @property
    def tray_manager(self) -> TrayManager | None:
        return self._tray_manager

    def set_tray_manager(self, tray_manager: TrayManager | None) -> None:
        self._tray_manager = tray_manager

    @property
    def startup_manager(self) -> StartupManager:
        return self._startup_manager

    def set_startup_manager(self, startup_manager: StartupManager) -> None:
        self._startup_manager = startup_manager

    def warmup_webengine(self) -> None:
        """백그라운드에서 Qt WebEngine 렌더러 프로세스를 미리 기동하여 첫 창 오픈 지연(Cold Start)을 방지합니다."""
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView

            view = QWebEngineView()
            view.setHtml("<html><body></body></html>")
            self._warmup_view = view
            # 1초 후 안전하게 정리하되 WebEngine 코어 라이브러리는 프로세스 메모리에 상주
            QTimer.singleShot(1000, self._release_warmup_view)
            logger.info("WebEngine preloaded for instant warm-start.")
        except Exception as exc:
            logger.debug("WebEngine warm-up skipped or unavailable: %s", exc)

    def _release_warmup_view(self) -> None:
        self._warmup_view = None

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

        body = getattr(window, "_body_widget", None)
        active_printer = getattr(body, "_active_printer", None) if body is not None else None
        html_view = getattr(body, "_html_view", None) if body is not None else None

        if active_printer is not None and html_view is not None and hasattr(html_view, "printFinished"):
            logger.info("Window has active HTML printing; retaining window until print completes.")
            self._pending_print_windows.add(window)

            def _on_print_finished(*_args: object) -> None:
                self._pending_print_windows.discard(window)
                try:
                    window.deleteLater()
                except RuntimeError:
                    pass
                if not self._windows and not self._pending_print_windows and not self._force_quitting:
                    settings = self._settings_service.load_settings()
                    if not (
                        self._tray_manager is not None
                        and self._tray_manager.is_available
                        and settings.minimize_to_tray_on_close
                    ):
                        self._wait_and_cleanup_threads()
                        app = QApplication.instance()
                        if app is not None:
                            app.quit()

            html_view.printFinished.connect(_on_print_finished, Qt.ConnectionType.SingleShotConnection)
        else:
            try:
                window.deleteLater()
            except RuntimeError:
                pass

        if not self._windows:
            if self._force_quitting:
                return

            settings = self._settings_service.load_settings()
            if (
                self._tray_manager is not None
                and self._tray_manager.is_available
                and settings.minimize_to_tray_on_close
            ):
                logger.info("All windows closed. Keeping EML Viewer running in background tray.")
                return

            if self._pending_print_windows:
                logger.info("Pending print operations still running; deferring application quit.")
                return

            self._wait_and_cleanup_threads()
            app = QApplication.instance()
            if app is not None:
                app.quit()

    def force_quit(self) -> None:
        """트레이 메뉴 또는 명시적 종료 요청 시 모든 창을 닫고 애플리케이션을 완전히 종료합니다."""
        self._force_quitting = True
        for win in list(self._windows) + list(self._pending_print_windows):
            try:
                win.close()
            except Exception as exc:
                logger.warning("Error closing window on force quit: %s", exc)

        self._pending_print_windows.clear()

        if self._tray_manager is not None:
            self._tray_manager.hide()

        self._wait_and_cleanup_threads()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def retain_thread(self, thread: object) -> None:
        """창이 닫혀도 실행 중인 백그라운드 스레드가 완료될 때까지 안전하게 수명을 보존합니다."""
        if hasattr(thread, "isRunning") and not thread.isRunning():
            return
        self._retained_threads.add(thread)
        if hasattr(thread, "finished"):
            thread.finished.connect(lambda: self._release_thread(thread))

    def _release_thread(self, thread: object) -> None:
        self._retained_threads.discard(thread)
        if hasattr(thread, "deleteLater"):
            try:
                thread.deleteLater()
            except Exception:
                pass

    def _wait_and_cleanup_threads(self) -> None:
        """앱 종료 전 보관된 백그라운드 스레드에 취소를 요청하고 안전하게 종료될 때까지 대기합니다."""
        for thread in list(self._retained_threads):
            if hasattr(thread, "cancel"):
                try:
                    thread.cancel()
                except Exception:
                    pass
            if hasattr(thread, "isRunning") and thread.isRunning():
                try:
                    thread.wait()
                except Exception:
                    pass
        self._retained_threads.clear()

    def handle_ipc_message(self, message: str) -> MainWindow:
        """싱글 인스턴스 IPC로 전달받은 파일 경로나 새 창 요청을 처리하고 전면으로 활성화합니다."""
        message = message.strip()
        window: MainWindow | None = None

        if message and message != "__NEW_WINDOW__":
            target_path = Path(message)
            if target_path.exists() and target_path.is_file():
                window = self.create_window(file_path=target_path)

        if window is None:
            window = self.create_window()

        if window.isMinimized():
            window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
        window.show()
        window.raise_()
        window.activateWindow()
        return window

    def broadcast_settings(self, new_settings: AppSettings) -> AppSettings:
        """설정(언어, 테마, 이미지 로드 옵션 등)을 저장하고 열려 있는 모든 창과 트레이에 실시간 반영합니다."""
        # 실제 바로가기 상태 또는 대상 경로가 다를 때 동기화 수행
        actual_is_enabled = self._startup_manager.is_startup_enabled()
        target_is_current = self._startup_manager.is_target_current() if actual_is_enabled else False
        startup_needs_sync = (new_settings.startup_with_windows != actual_is_enabled) or (
            new_settings.startup_with_windows and not target_is_current
        )
        shortcut_backup: bytes | None = None

        if startup_needs_sync:
            shortcut_backup = self._startup_manager.backup_shortcut()
            actual_startup = new_settings.startup_with_windows
            try:
                ok = self._startup_manager.set_startup_enabled(new_settings.startup_with_windows)
                if not ok:
                    actual_startup = self._startup_manager.is_startup_enabled()
            except Exception as exc:
                logger.warning("Failed to sync startup shortcut: %s", exc)
                actual_startup = self._startup_manager.is_startup_enabled()

            if actual_startup != new_settings.startup_with_windows:
                from dataclasses import replace
                new_settings = replace(new_settings, startup_with_windows=actual_startup)

        try:
            self._settings_service.save_settings(new_settings)
        except Exception:
            if startup_needs_sync:
                try:
                    self._startup_manager.restore_shortcut(shortcut_backup)
                except Exception as rollback_exc:
                    logger.warning("Failed to rollback startup shortcut: %s", rollback_exc)
            raise
        set_language(new_settings.language)

        app = QApplication.instance()
        if app is not None:
            apply_theme(app, new_settings.theme)

        # 트레이 상태 동기화
        if self._tray_manager is not None:
            self._tray_manager.update_action_states()

        for win in self._windows:
            try:
                win.apply_settings(new_settings)
            except Exception as exc:
                logger.warning("Failed to broadcast settings to window: %s", exc)

        return new_settings
