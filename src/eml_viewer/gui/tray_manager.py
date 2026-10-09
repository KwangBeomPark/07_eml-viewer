from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from eml_viewer.gui.i18n import tr
from eml_viewer.services.settings_service import SettingsService
from eml_viewer.services.startup_manager import StartupManager

if TYPE_CHECKING:
    from eml_viewer.gui.window_manager import WindowManager

logger = logging.getLogger(__name__)


class TrayManager(QObject):
    """시스템 트레이 아이콘 및 메뉴를 관리하여 백그라운드 프리로드 및 빠른 실행을 지원합니다."""

    def __init__(
        self,
        window_manager: WindowManager,
        startup_manager: StartupManager | None = None,
        settings_service: SettingsService | None = None,
        icon: QIcon | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._window_manager = window_manager
        self._startup_manager = startup_manager or StartupManager()
        self._settings_service = settings_service or SettingsService()

        self._tray_icon: QSystemTrayIcon | None = None
        self._menu: QMenu | None = None
        self._action_new_window: QAction | None = None
        self._startup_action: QAction | None = None
        self._action_exit: QAction | None = None
        self._icon = icon

        if QSystemTrayIcon.isSystemTrayAvailable():
            self._setup_tray()
        else:
            logger.warning("System tray is not available on this platform/session.")

    @property
    def is_available(self) -> bool:
        return (
            self._tray_icon is not None
            and not self._tray_icon.icon().isNull()
            and QSystemTrayIcon.isSystemTrayAvailable()
        )

    def show(self) -> None:
        if self._tray_icon is not None:
            self._tray_icon.show()

    def hide(self) -> None:
        if self._tray_icon is not None:
            self._tray_icon.hide()

    def show_message(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
        timeout_ms: int = 3000,
    ) -> None:
        if self._tray_icon is not None and self._tray_icon.isVisible():
            self._tray_icon.showMessage(title, message, icon, timeout_ms)

    def update_action_states(self) -> None:
        """설정 변경(언어, 시작프로그램 등)에 따라 트레이 메뉴 항목들의 텍스트 및 체크 상태를 갱신합니다."""
        if self._tray_icon is not None:
            self._tray_icon.setToolTip(tr("tray.tooltip"))
        if self._action_new_window is not None:
            self._action_new_window.setText(tr("tray.open_new_window"))
        if self._startup_action is not None:
            self._startup_action.setText(tr("tray.startup_with_windows"))
            is_enabled = self._startup_manager.is_startup_enabled()
            self._startup_action.blockSignals(True)
            self._startup_action.setChecked(is_enabled)
            self._startup_action.blockSignals(False)
        if self._action_exit is not None:
            self._action_exit.setText(tr("tray.exit"))

    def _setup_tray(self) -> None:
        app = QApplication.instance()
        icon = self._icon
        if (icon is None or icon.isNull()) and app is not None and not app.windowIcon().isNull():
            icon = app.windowIcon()
        if (icon is None or icon.isNull()) and app is not None and app.style() is not None:
            icon = app.style().standardIcon(QStyle.StandardPixmap.SP_DesktopIcon)

        self._tray_icon = QSystemTrayIcon(icon or QIcon(), self)
        self._tray_icon.setToolTip(tr("tray.tooltip"))

        # 트레이 컨텍스트 메뉴 구성
        self._menu = QMenu()

        self._action_new_window = QAction(tr("tray.open_new_window"), self)
        self._action_new_window.triggered.connect(self._on_open_new_window)
        self._menu.addAction(self._action_new_window)

        self._menu.addSeparator()

        self._startup_action = QAction(tr("tray.startup_with_windows"), self)
        self._startup_action.setCheckable(True)
        self._startup_action.setChecked(self._startup_manager.is_startup_enabled())
        self._startup_action.toggled.connect(self._on_toggle_startup)
        self._menu.addAction(self._startup_action)

        self._menu.addSeparator()

        self._action_exit = QAction(tr("tray.exit"), self)
        self._action_exit.triggered.connect(self._on_exit)
        self._menu.addAction(self._action_exit)

        self._tray_icon.setContextMenu(self._menu)
        self._tray_icon.activated.connect(self._on_tray_activated)

    def _on_open_new_window(self) -> None:
        self._window_manager.create_window()

    def _on_toggle_startup(self, checked: bool) -> None:
        shortcut_backup = self._startup_manager.backup_shortcut()
        old_is_enabled = self._startup_manager.is_startup_enabled()
        ok = self._startup_manager.set_startup_enabled(checked)
        actual = self._startup_manager.is_startup_enabled() if not ok else checked
        if not ok and self._startup_action is not None:
            self._startup_action.blockSignals(True)
            self._startup_action.setChecked(actual)
            self._startup_action.blockSignals(False)

        settings = self._settings_service.load_settings()
        if settings.startup_with_windows != actual:
            from dataclasses import replace
            new_settings = replace(settings, startup_with_windows=actual)
            try:
                self._settings_service.save_settings(new_settings)
            except Exception as exc:
                logger.error("Failed to save settings on startup toggle: %s", exc)
                # 롤백: 바로가기 원본 파일 바이트 복원 및 메뉴 체크 상태 복원
                try:
                    self._startup_manager.restore_shortcut(shortcut_backup)
                except Exception:
                    pass
                if self._startup_action is not None:
                    self._startup_action.blockSignals(True)
                    self._startup_action.setChecked(old_is_enabled)
                    self._startup_action.blockSignals(False)
                return
        logger.info("Startup with Windows set to: %s (requested: %s)", actual, checked)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._activate_or_open_window()

    def _activate_or_open_window(self) -> None:
        windows = self._window_manager.windows
        if windows:
            last_win = windows[-1]
            if last_win.isMinimized():
                last_win.setWindowState(last_win.windowState() & ~Qt.WindowState.WindowMinimized)
            last_win.show()
            last_win.raise_()
            last_win.activateWindow()
        else:
            self._window_manager.create_window()

    def _on_exit(self) -> None:
        logger.info("User requested exit from tray context menu.")
        self.hide()
        self._window_manager.force_quit()
