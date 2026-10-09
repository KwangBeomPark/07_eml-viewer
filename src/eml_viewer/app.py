from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

from eml_viewer import __version__
from eml_viewer.gui.i18n import tr

logger = logging.getLogger(__name__)


def _show_unhandled_exception(exc_type, exc_value, exc_traceback) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logging.error(
        "Unhandled exception",
        exc_info=(exc_type, exc_value, exc_traceback),
    )

    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance()
        if app is None:
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        QMessageBox.critical(
            None,
            tr("app.unhandled_error.title"),
            tr("app.unhandled_error.body", details=details),
        )
    except Exception:
        sys.__excepthook__(exc_type, exc_value, exc_traceback)


def _resource_path(relative_path: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base_path / relative_path


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    sys.excepthook = _show_unhandled_exception

    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
    except ModuleNotFoundError:
        print(tr("app.pyside_missing"), file=sys.stderr)
        return 1

    from eml_viewer.app_identity import DISPLAY_NAME, WINDOWS_APP_ID
    from eml_viewer.gui.i18n import set_language
    from eml_viewer.gui.theme import apply_theme
    from eml_viewer.gui.tray_manager import TrayManager
    from eml_viewer.gui.window_manager import WindowManager
    from eml_viewer.services.attachment_service import AttachmentService
    from eml_viewer.services.eml_parser import EmlParser
    from eml_viewer.services.file_operation_service import FileOperationService
    from eml_viewer.services.forward_service import ForwardService
    from eml_viewer.services.settings_service import SettingsService
    from eml_viewer.services.single_instance import (
        CMD_NEW_WINDOW,
        SingleInstanceClient,
        SingleInstanceServer,
    )
    from eml_viewer.services.startup_manager import StartupManager
    from eml_viewer.services.update_service import UpdateService

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
        except Exception:
            pass

    # 인자 분석
    is_tray_mode = any(arg in {"--tray", "--preload"} for arg in argv[1:])
    target_file: Path | None = None
    for arg in argv[1:]:
        if arg in {"--tray", "--preload"}:
            continue
        candidate = Path(arg)
        if candidate.suffix.lower() in {".eml", ".msg"}:
            target_file = candidate.resolve()
            break

    # QApplication 초기화
    app = QApplication(argv)
    app.setApplicationName(DISPLAY_NAME)
    app.setOrganizationName("PL_Suite")
    app.setApplicationVersion(__version__)
    icon_path = _resource_path("assets/app.ico")
    app_icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    # 1. 싱글 인스턴스 검사: 이미 백그라운드/기존 프로세스가 실행 중인지 확인
    if is_tray_mode:
        # 백그라운드 모드로 추가 실행을 요청했을 때 이미 서버가 있으면 조용히 종료
        if SingleInstanceClient.send_to_primary_instance(""):
            logger.info("Primary instance already active. Secondary tray process exiting.")
            return 0
    else:
        # 파일 열기 또는 일반 실행 시도 시 기존 인스턴스로 명령 전달
        payload = str(target_file) if target_file is not None else CMD_NEW_WINDOW
        if SingleInstanceClient.send_to_primary_instance(payload):
            logger.info("Command forwarded to running EML Viewer instance. Exiting.")
            return 0

    # 2. 최초 인스턴스 (Primary Instance) 진입:
    # Windows 전용 네임드 뮤텍스 생성 (인스톨러에서 실행 중인 프로세스 감지용)
    mutex_handle = None
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            CreateMutex = ctypes.windll.kernel32.CreateMutexW
            CreateMutex.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            CreateMutex.restype = wintypes.HANDLE
            mutex_handle = CreateMutex(None, False, "EmlViewerMutex")
        except Exception as exc:
            logging.warning(f"네임드 뮤텍스 생성 실패: {exc}")

    # 모든 창이 닫혀도 시스템 트레이에 상주할 수 있도록 설정
    app.setQuitOnLastWindowClosed(False)

    settings_service = SettingsService()
    settings = settings_service.load_settings()
    set_language(settings.language)
    apply_theme(app, settings.theme)

    parser = EmlParser()
    file_operation_service = FileOperationService()
    startup_manager = StartupManager()

    window_manager = WindowManager(
        parser=parser,
        settings_service=settings_service,
        file_operation_service=file_operation_service,
        attachment_service=AttachmentService(parser, file_operation_service),
        forward_service=ForwardService(),
        update_service=UpdateService(),
        startup_manager=startup_manager,
    )
    app.aboutToQuit.connect(window_manager._wait_and_cleanup_threads)

    # 싱글 인스턴스 IPC 서버 시작 (배타적 락으로 중복 실행 방지)
    ipc_server = SingleInstanceServer(parent=app)
    if not ipc_server.start():
        logger.info("Primary server already claimed by concurrent instance. Forwarding payload...")
        import time

        payload = "" if is_tray_mode else (str(target_file) if target_file is not None else CMD_NEW_WINDOW)
        forwarded = False
        for _ in range(20):
            time.sleep(0.1)
            if SingleInstanceClient.send_to_primary_instance(payload, timeout_ms=300):
                forwarded = True
                break
        if forwarded:
            logger.info("Successfully forwarded to concurrent primary instance. Exiting.")
            return 0
        logger.warning("Could not forward payload to concurrent instance; continuing as secondary.")

    ipc_server.message_received.connect(window_manager.handle_ipc_message)

    # 트레이 아이콘 관리자 시작
    tray_manager = TrayManager(
        window_manager=window_manager,
        startup_manager=startup_manager,
        settings_service=settings_service,
        icon=app_icon,
        parent=app,
    )
    window_manager.set_tray_manager(tray_manager)
    tray_manager.show()

    if is_tray_mode:
        if tray_manager.is_available:
            # 백그라운드 프리로드 모드: 창을 열지 않고 WebEngine만 사전 초기화
            logger.info("EML Viewer running in background tray preload mode.")
            window_manager.warmup_webengine()
        else:
            # 트레이가 지원되지 않는 환경에서는 숨은 프로세스로 남지 않도록 일반 창으로 전환
            logger.warning("System tray is unavailable; opening standard window instead of tray mode.")
            window_manager.create_window(file_path=target_file)
    else:
        # 일반 모드: 초기 창 생성
        window_manager.create_window(file_path=target_file)

    exit_code = app.exec()

    # 정리
    ipc_server.stop()
    if mutex_handle:
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(mutex_handle)
        except Exception:
            pass

    return exit_code
