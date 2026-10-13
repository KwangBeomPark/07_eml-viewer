from __future__ import annotations

import atexit
import logging
import os
import re
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QEvent, QRect, Qt, QTimer, QUrl, QThread, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QMenu,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtPrintSupport import QPrinter

from eml_viewer.gui import dialogs
from eml_viewer.gui.attachment_widgets import AttachmentPanel
from eml_viewer.gui.i18n import tr
from eml_viewer.gui.message_widgets import MessageBodyWidget
from eml_viewer.gui.metadata_widgets import CopyableLineEdit
from eml_viewer.gui.settings_dialog import SettingsDialog
from eml_viewer.gui.theme import apply_theme
from eml_viewer.gui.ui_helpers import ElidedLabel, display_safe_text, printer_icon, safe_tooltip
from eml_viewer.models.attachment_data import AttachmentInfo
from eml_viewer.models.email_data import ParsedEmail
from eml_viewer.services.attachment_policy import is_dangerous_extension
from eml_viewer.services.attachment_service import AttachmentService
from eml_viewer.services.eml_parser import EmlParser
from eml_viewer.services.error_service import ErrorService
from eml_viewer.services.file_operation_service import FileOperationService
from eml_viewer.services.folder_navigation import FolderNavigationService
from eml_viewer.services.forward_service import ForwardConfigError, ForwardService
from eml_viewer.services.settings_service import SettingsService
from eml_viewer.services.update_service import UpdateCheckResult, UpdateService

logger = logging.getLogger(__name__)
_orphaned_email_threads: set[QThread] = set()
_orphaned_print_windows: set[object] = set()


def _safe_message_lines(value: object) -> str:
    """Render untrusted message text safely while retaining intentional line breaks."""
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(display_safe_text(line) for line in normalized.split("\n"))


def _release_orphaned_email_thread(thread: QThread) -> None:
    if thread not in _orphaned_email_threads:
        return
    _orphaned_email_threads.discard(thread)
    thread.deleteLater()


def _wait_for_orphaned_email_threads() -> None:
    """Drain parser workers owned by standalone windows during application shutdown."""
    for thread in list(_orphaned_email_threads):
        if thread.isRunning():
            thread.wait()
        _release_orphaned_email_thread(thread)


class EmailLoadThread(QThread):
    """Parse one email without touching any Qt widgets."""

    loaded = Signal(int, object, object)
    failed = Signal(int, object)

    def __init__(self, parser: EmlParser, request_id: int, path: str | Path) -> None:
        super().__init__()
        self._parser = parser
        self._request_id = request_id
        self._path = path

    def run(self) -> None:
        try:
            result = self._parser.parse_file(self._path)
        except Exception as exc:
            self.failed.emit(self._request_id, exc)
        else:
            self.loaded.emit(self._request_id, self._path, result)


class DownloadThread(QThread):
    progress = Signal(int, int)  # downloaded, total
    download_finished = Signal(str)
    failed = Signal(str)

    def __init__(self, service: UpdateService, url: str, dest_path: str) -> None:
        super().__init__()
        self._service = service
        self._url = url
        self._dest_path = dest_path
        import threading
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            self._service.download_installer(
                url=self._url,
                dest_path=self._dest_path,
                progress_callback=self._progress_callback,
                cancel_event=self._cancel_event,
            )
            if not self._cancel_event.is_set():
                self.download_finished.emit(self._dest_path)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _progress_callback(self, downloaded: int, total: int) -> None:
        self.progress.emit(downloaded, total)


class UpdateCheckThread(QThread):
    check_finished = Signal(object)
    failed = Signal(str)

    def __init__(self, service: UpdateService) -> None:
        super().__init__()
        self._service = service

    def run(self) -> None:
        try:
            self.check_finished.emit(self._service.check_for_updates())
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    """EML Viewer의 메인 화면입니다."""

    def __init__(
        self,
        parser: EmlParser,
        attachment_service: AttachmentService,
        settings_service: SettingsService,
        file_operation_service: FileOperationService,
        forward_service: ForwardService | None = None,
        update_service: UpdateService | None = None,
        window_manager: object | None = None,
        auto_check_update: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._parser = parser
        self._attachment_service = attachment_service
        self._settings_service = settings_service
        self._file_operation_service = file_operation_service
        self._forward_service = forward_service or ForwardService()
        self._update_service = update_service or UpdateService()
        self._window_manager = window_manager
        self._child_windows: list[MainWindow] = []
        self._current_email: ParsedEmail | None = None
        self._folder_emails: list[Path] = []
        self._folder_navigation = FolderNavigationService()
        self._folder_watcher = QFileSystemWatcher(self)
        self._folder_watcher.directoryChanged.connect(self._on_folder_changed)
        self._folder_change_timer = QTimer(self)
        self._folder_change_timer.setSingleShot(True)
        self._folder_change_timer.setInterval(200)
        self._folder_change_timer.timeout.connect(self._refresh_folder_navigation_after_change)
        self._current_folder_index: int = -1
        self._pending_navigation_index: int | None = None
        self._pending_navigation_path: Path | None = None
        self._pending_navigation_active = False
        self._current_email_path: Path | None = None
        self._download_thread: DownloadThread | None = None
        self._update_check_thread: UpdateCheckThread | None = None
        self._email_load_thread: EmailLoadThread | None = None
        self._pending_email_load: tuple[int, str | Path] | None = None
        self._email_load_request_id = 0
        self._email_load_closed = False
        self._close_event_started = False
        self._available_update_result: UpdateCheckResult | None = None
        self._session_temp_dir = Path(tempfile.mkdtemp(prefix="eml_temp_"))
        temp_dir_str = str(self._session_temp_dir)
        self._cleanup_session_callback = lambda: shutil.rmtree(temp_dir_str, ignore_errors=True)
        atexit.register(self._cleanup_session_callback)
        self.setAcceptDrops(True)

        copied_tooltip = tr("copy.feedback")
        self._subject_edit = CopyableLineEdit(tr("copy.subject"), copied_tooltip, self)
        self._sender_edit = CopyableLineEdit(tr("copy.sender"), copied_tooltip, self)
        self._to_edit = CopyableLineEdit(tr("copy.to"), copied_tooltip, self)
        self._cc_edit = CopyableLineEdit(tr("copy.cc"), copied_tooltip, self)
        self._date_edit = CopyableLineEdit(tr("copy.date"), copied_tooltip, self)
        self._current_file_label = QLabel(self)
        self._forward_button = QPushButton(self)
        self._body_widget = MessageBodyWidget(self)
        self._attachment_panel = AttachmentPanel(self)
        self._body_widget.print_busy_changed.connect(self._update_print_actions)

        self.setWindowTitle("EML Viewer")
        self._build_actions()
        self._update_print_actions()
        self._build_ui()
        self._retranslate_ui()
        self._restore_window_geometry()
        self._body_widget.set_remote_images_auto_load(
            self._settings_service.load_settings().auto_load_remote_images
        )

        self._attachment_panel.save_requested.connect(self._save_attachments)
        self._attachment_panel.open_requested.connect(self._open_attachments)
        self._subject_edit.copy_requested.connect(self._copy_to_clipboard)
        self._sender_edit.copy_requested.connect(self._copy_to_clipboard)
        self._to_edit.copy_requested.connect(self._copy_to_clipboard)
        self._cc_edit.copy_requested.connect(self._copy_to_clipboard)
        self._date_edit.copy_requested.connect(self._copy_to_clipboard)
        self._forward_button.clicked.connect(self._forward_current_email)
        self._body_widget.open_in_browser_requested.connect(self._open_in_browser)
        if auto_check_update:
            self._start_background_update_check()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    suffix = Path(url.toLocalFile()).suffix.lower()
                    if suffix in {".eml", ".msg"}:
                        event.acceptProposedAction()
                        return
        event.ignore()

    def dropEvent(self, event) -> None:
        valid_paths: list[Path] = []
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.is_file() and p.suffix.lower() in {".eml", ".msg"}:
                        valid_paths.append(p)

        if not valid_paths:
            event.ignore()
            return

        event.acceptProposedAction()
        self.load_email_async(valid_paths[0])

        for remaining_path in valid_paths[1:]:
            if self._window_manager is not None and hasattr(self._window_manager, "create_window"):
                self._window_manager.create_window(file_path=remaining_path)
            else:
                win = MainWindow(
                    parser=self._parser,
                    attachment_service=self._attachment_service,
                    settings_service=self._settings_service,
                    file_operation_service=self._file_operation_service,
                    forward_service=self._forward_service,
                    update_service=self._update_service,
                    auto_check_update=False,
                )
                win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
                self._child_windows.append(win)
                win.destroyed.connect(lambda checked=False, w=win: self._child_windows.remove(w) if w in self._child_windows else None)
                win.load_email_async(remaining_path)
                win.show()

    def _build_actions(self) -> None:
        self._new_window_action = QAction(self)
        self._new_window_action.setShortcut("Ctrl+N")
        self._new_window_action.triggered.connect(self._open_new_window)

        self._open_action = QAction(self)
        self._open_action.setShortcut("Ctrl+O")
        self._open_action.triggered.connect(self._open_file)

        self._save_as_action = QAction(self)
        self._save_as_action.setShortcut("Ctrl+Shift+S")
        self._save_as_action.triggered.connect(self._save_as)

        self._export_pdf_action = QAction(self)
        self._export_pdf_action.setShortcut("Ctrl+Shift+P")
        self._export_pdf_action.triggered.connect(self._export_as_pdf)

        self._exit_action = QAction(self)
        self._exit_action.setShortcut("Alt+F4")
        self._exit_action.triggered.connect(self.close)

        self._quit_action = QAction(self)
        self._quit_action.setShortcut("Ctrl+Q")
        self._quit_action.triggered.connect(self._on_exit_action_triggered)

        self._open_browser_action = QAction(self)
        self._open_browser_action.setShortcut("Ctrl+B")
        self._open_browser_action.triggered.connect(self._open_in_browser)

        self._print_action = QAction(self)
        self._print_action.setShortcut("Ctrl+P")
        self._print_action.triggered.connect(self._print_current_message)

        self._view_source_action = QAction(self)
        self._view_source_action.setShortcut("Ctrl+U")
        self._view_source_action.triggered.connect(self._view_message_source)

        self._prev_email_action = QAction(self)
        self._prev_email_action.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ArrowBack))
        self._prev_email_action.setShortcut("Alt+Left")
        self._prev_email_action.triggered.connect(self._navigate_prev_email)
        self._prev_email_action.setEnabled(False)

        self._next_email_action = QAction(self)
        self._next_email_action.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ArrowForward))
        self._next_email_action.setShortcut("Alt+Right")
        self._next_email_action.triggered.connect(self._navigate_next_email)
        self._next_email_action.setEnabled(False)

        self._settings_action = QAction(self)
        self._settings_action.triggered.connect(self._open_settings)

        self._find_action = QAction(self)
        self._find_action.setShortcut("Ctrl+F")
        self._find_action.triggered.connect(self._body_widget.show_search_bar)

        self._find_next_action = QAction(self)
        self._find_next_action.setShortcut("F3")
        self._find_next_action.triggered.connect(self._body_widget.find_next)

        self._find_prev_action = QAction(self)
        self._find_prev_action.setShortcut("Shift+F3")
        self._find_prev_action.triggered.connect(self._body_widget.find_previous)

        self._file_menu = self.menuBar().addMenu("")
        self._file_menu.addAction(self._new_window_action)
        self._file_menu.addAction(self._open_action)
        self._recent_files_menu = self._file_menu.addMenu("")
        self._file_menu.addAction(self._save_as_action)
        self._file_menu.addAction(self._export_pdf_action)
        self._file_menu.addSeparator()
        self._file_menu.addAction(self._open_browser_action)
        self._file_menu.addAction(self._print_action)
        self._file_menu.addSeparator()
        self._file_menu.addAction(self._settings_action)
        self._file_menu.addSeparator()
        self._file_menu.addAction(self._exit_action)
        self._file_menu.addAction(self._quit_action)

        self._view_menu = self.menuBar().addMenu("")
        self._view_menu.addAction(self._view_source_action)
        self._view_menu.addSeparator()
        self._view_menu.addAction(self._prev_email_action)
        self._view_menu.addAction(self._next_email_action)

        self._edit_menu = self.menuBar().addMenu("")
        self._edit_menu.addAction(self._find_action)
        self._edit_menu.addAction(self._find_next_action)
        self._edit_menu.addAction(self._find_prev_action)

        self._update_action = QAction(self)
        self._update_action.triggered.connect(self._check_for_updates)

        self._help_menu = self.menuBar().addMenu("")
        self._help_menu.addAction(self._update_action)

        self._toolbar = self.addToolBar("")
        self._toolbar.setObjectName("mainToolbar")
        self._toolbar.setMovable(False)
        self._toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._open_action.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_DialogOpenButton))
        self._save_as_action.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_DialogSaveButton))
        self._export_pdf_action.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_FileIcon))
        self._print_action.setIcon(
            printer_icon(self.palette(), device_pixel_ratio=self.devicePixelRatioF())
        )
        self._toolbar.addAction(self._open_action)
        self._toolbar.addAction(self._save_as_action)
        self._toolbar.addAction(self._export_pdf_action)
        self._toolbar.addAction(self._print_action)
        self._toolbar.addSeparator()
        self._toolbar.addAction(self._prev_email_action)
        self._toolbar.addAction(self._next_email_action)

    def _build_ui(self) -> None:
        # Retain the legacy label object for callers/tests, but the filename is
        # displayed in the message summary and this standalone child must not float.
        self._current_file_label.hide()
        self._open_button = QToolButton(self)
        self._open_button.setObjectName("actionPrimary")
        self._open_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._open_button.setMinimumHeight(36)
        self._open_button.setIcon(self._open_action.icon())
        self._open_button.clicked.connect(self._open_action.trigger)
        self._forward_button.setEnabled(False)

        self._update_banner = QWidget(self)
        self._update_banner.setObjectName("updateBanner")
        self._update_banner_label = QLabel("", self)
        self._update_banner_download_button = QPushButton(self)
        self._update_banner_close_button = QPushButton(self)
        self._update_banner_download_button.clicked.connect(self._download_available_update)
        self._update_banner_close_button.clicked.connect(self._update_banner.hide)

        update_banner_layout = QHBoxLayout(self._update_banner)
        update_banner_layout.setContentsMargins(10, 6, 10, 6)
        update_banner_layout.addWidget(self._update_banner_label, stretch=1)
        update_banner_layout.addWidget(self._update_banner_download_button)
        update_banner_layout.addWidget(self._update_banner_close_button)
        self._update_banner.setVisible(False)

        self._metadata_group = QGroupBox(self)
        self._metadata_group.setObjectName("metadataDetails")
        metadata_layout = QFormLayout(self._metadata_group)
        self._subject_label = QLabel(self)
        self._sender_label = QLabel(self)
        self._to_label = QLabel(self)
        self._cc_label = QLabel(self)
        self._date_label = QLabel(self)
        metadata_layout.addRow(self._subject_label, self._subject_edit)
        metadata_layout.addRow(self._sender_label, self._sender_edit)
        metadata_layout.addRow(self._to_label, self._to_edit)
        metadata_layout.addRow(self._cc_label, self._cc_edit)
        metadata_layout.addRow(self._date_label, self._date_edit)
        self._metadata_group.setVisible(False)
        self._metadata_scroll_area = QScrollArea(self)
        self._metadata_scroll_area.setObjectName("metadataDetailsScrollArea")
        self._metadata_scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self._metadata_scroll_area.setWidgetResizable(True)
        self._metadata_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._metadata_scroll_area.setMaximumHeight(132)
        self._metadata_scroll_area.setWidget(self._metadata_group)
        self._metadata_scroll_area.setVisible(False)

        self._subject_summary = QLabel(self)
        self._subject_summary.setObjectName("messageSubject")
        self._subject_summary.setTextFormat(Qt.TextFormat.PlainText)
        self._subject_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self._subject_summary.setWordWrap(True)
        self._subject_summary.setMaximumHeight(52)
        self._subject_summary.setToolTip(safe_tooltip(""))
        self._summary_meta = ElidedLabel(self)
        self._summary_meta.setObjectName("secondaryText")
        self._details_toggle = QToolButton(self)
        self._details_toggle.setObjectName("metadataDetailsToggle")
        self._details_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._details_toggle.setMinimumHeight(32)
        self._details_toggle.setCheckable(True)
        self._details_toggle.setChecked(False)
        self._details_toggle.toggled.connect(self._set_details_visible)
        self._header_copy_menu = self._subject_summary
        self._subject_summary.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._subject_summary.customContextMenuRequested.connect(self._show_summary_copy_menu)
        self._content_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self._content_splitter.addWidget(self._body_widget)
        self._content_splitter.addWidget(self._attachment_panel)
        self._content_splitter.setCollapsible(1, False)
        self._content_splitter.setHandleWidth(0)
        self._content_splitter.setStretchFactor(0, 3)
        self._content_splitter.setStretchFactor(1, 1)

        self._message_page = QWidget(self)
        message_layout = QVBoxLayout(self._message_page)
        message_layout.setContentsMargins(8, 4, 8, 4)
        header_layout = QVBoxLayout()
        summary_top = QHBoxLayout()
        summary_top.addWidget(self._subject_summary, 1)
        summary_top.addWidget(self._forward_button)
        header_layout.addLayout(summary_top)
        summary_bottom = QHBoxLayout()
        summary_bottom.addWidget(self._summary_meta, 1)
        summary_bottom.addWidget(self._details_toggle)
        header_layout.addLayout(summary_bottom)
        header_container = QWidget(self._message_page)
        header_container.setObjectName("messageHeader")
        header_container.setLayout(header_layout)
        message_layout.addWidget(header_container)
        message_layout.addWidget(self._metadata_scroll_area)
        message_layout.addWidget(self._content_splitter, 1)

        self._welcome_page = QWidget(self)
        welcome_layout = QVBoxLayout(self._welcome_page)
        welcome_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._welcome_icon = QLabel("✉", self._welcome_page)
        self._welcome_icon.setObjectName("welcomeIcon")
        self._welcome_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._welcome_heading = QLabel(self._welcome_page)
        self._welcome_heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._welcome_heading.setObjectName("welcomeHeading")
        self._welcome_button = self._open_button
        self._welcome_button.setParent(self._welcome_page)
        self._welcome_button.setAccessibleName(tr("welcome.open"))
        self._welcome_hint = QLabel(self._welcome_page)
        self._welcome_hint.setObjectName("welcomeHint")
        self._welcome_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._welcome_loading = QLabel(self._welcome_page)
        self._welcome_loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for widget in (self._welcome_icon, self._welcome_heading, self._welcome_button, self._welcome_hint, self._welcome_loading):
            welcome_layout.addWidget(widget)
        self._welcome_loading.hide()

        self._content_stack = QStackedWidget(self)
        self._content_stack.addWidget(self._welcome_page)
        self._content_stack.addWidget(self._message_page)
        self._content_stack.setCurrentWidget(self._welcome_page)

        content_layout = QVBoxLayout()
        content_layout.addWidget(self._update_banner)
        content_layout.addWidget(self._content_stack, stretch=1)

        central_widget = QWidget(self)
        central_widget.setLayout(content_layout)
        self.setCentralWidget(central_widget)

    def apply_settings(self, new_settings) -> None:
        """새 설정을 적용하여 UI 언어, 테마, 이미지 로드 옵션을 갱신합니다."""
        self.retranslate_ui()
        self._body_widget.set_remote_images_auto_load(new_settings.auto_load_remote_images)

    def retranslate_ui(self) -> None:
        self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        self._print_action.setIcon(
            printer_icon(self.palette(), device_pixel_ratio=self.devicePixelRatioF())
        )
        self._new_window_action.setText(tr("action.new_window"))
        self._open_action.setText(tr("button.open_eml"))
        self._save_as_action.setText(tr("action.save_email"))
        self._export_pdf_action.setText(tr("action.export_pdf"))
        self._open_browser_action.setText(tr("button.open_browser"))
        self._print_action.setText(tr("action.print"))
        self._view_source_action.setText(tr("action.view_source"))
        self._prev_email_action.setText(tr("action.prev_email"))
        self._next_email_action.setText(tr("action.next_email"))
        self._settings_action.setText(tr("menu.settings"))
        self._exit_action.setText(tr("menu.close"))
        self._quit_action.setText(tr("menu.quit"))
        self._find_action.setText(tr("menu.find"))
        self._find_next_action.setText(tr("find.next"))
        self._find_prev_action.setText(tr("find.previous"))
        self._update_action.setText(tr("menu.update_check"))
        self._file_menu.setTitle(tr("menu.file"))
        self._recent_files_menu.setTitle(tr("menu.recent_files"))
        self._view_menu.setTitle(tr("menu.view"))
        self._edit_menu.setTitle(tr("menu.edit"))
        self._help_menu.setTitle(tr("menu.help"))
        self._toolbar.setWindowTitle(tr("toolbar.main"))
        self._open_button.setText(tr("welcome.open"))
        self._open_action.setIconText(tr("toolbar.open"))
        self._open_action.setToolTip(tr("tooltip.open"))
        self._save_as_action.setIconText(tr("toolbar.save_email"))
        self._save_as_action.setToolTip(tr("tooltip.save_email"))
        self._export_pdf_action.setIconText(tr("toolbar.pdf"))
        self._export_pdf_action.setToolTip(tr("tooltip.pdf"))
        self._print_action.setIconText(tr("toolbar.print"))
        self._print_action.setToolTip(tr("tooltip.print"))
        self._prev_email_action.setIconText("")
        self._prev_email_action.setToolTip(tr("tooltip.prev_email"))
        self._next_email_action.setIconText("")
        self._next_email_action.setToolTip(tr("tooltip.next_email"))
        for action in (self._prev_email_action, self._next_email_action):
            button = self._toolbar.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._forward_button.setText(tr("forward.current"))
        self._welcome_heading.setText(tr("welcome.heading"))
        self._welcome_hint.setText(tr("welcome.drop_hint"))
        self._welcome_button.setAccessibleName(tr("welcome.open"))
        self._details_toggle.setText(tr("metadata.details"))
        self._details_toggle.setAccessibleName(tr("metadata.details"))
        self._update_banner_download_button.setText(tr("button.download"))
        self._update_banner_close_button.setText(tr("button.close"))
        self._metadata_group.setTitle(tr("label.metadata.group"))
        self._subject_label.setText(tr("label.metadata.subject"))
        self._sender_label.setText(tr("label.metadata.sender"))
        self._to_label.setText(tr("label.metadata.to"))
        self._cc_label.setText(tr("label.metadata.cc"))
        self._date_label.setText(tr("label.metadata.date"))
        self._subject_edit.set_copy_tooltip(tr("copy.subject"))
        self._sender_edit.set_copy_tooltip(tr("copy.sender"))
        self._to_edit.set_copy_tooltip(tr("copy.to"))
        self._cc_edit.set_copy_tooltip(tr("copy.cc"))
        self._date_edit.set_copy_tooltip(tr("copy.date"))
        for field in (
            self._subject_edit,
            self._sender_edit,
            self._to_edit,
            self._cc_edit,
            self._date_edit,
        ):
            field.set_copied_tooltip(tr("copy.feedback"))
        self._body_widget.retranslate_ui()
        self._attachment_panel.retranslate_ui()
        self._update_recent_files_menu()
        if self._current_email is None:
            self._current_file_label.setText(tr("label.current_file.none"))
            self.statusBar().showMessage(tr("status.select_eml"))
        if self._available_update_result is not None:
            self._set_update_banner_text(self._available_update_result)
        self._update_window_title()

    def _update_recent_files_menu(self) -> None:
        self._recent_files_menu.clear()
        recent_files = self._settings_service.load_settings().recent_files
        existing_files = [f for f in recent_files if Path(f).exists()]
        if not existing_files:
            empty_action = self._recent_files_menu.addAction(tr("menu.recent_empty"))
            empty_action.setEnabled(False)
            return

        for file_path in existing_files:
            path_obj = Path(file_path)
            display_name = f"{path_obj.parent.name}/{path_obj.name}" if path_obj.parent.name else path_obj.name
            action = self._recent_files_menu.addAction(display_safe_text(display_name))
            action.setToolTip(safe_tooltip(file_path))
            action.setStatusTip(display_safe_text(file_path))
            action.triggered.connect(lambda checked=False, p=file_path: self.load_email_async(p))

        self._recent_files_menu.addSeparator()
        clear_action = self._recent_files_menu.addAction(tr("menu.recent_clear"))
        clear_action.triggered.connect(self._clear_recent_files)

    def _update_window_title(self) -> None:
        if self._current_email is not None:
            raw_subject = self._current_email.subject or ""
            subject = display_safe_text(re.sub(r"[\r\n\t]+", " ", raw_subject)).strip()
            display_subject = subject if subject else tr("app.untitled_subject")
            self.setWindowTitle(f"{display_subject} - EML Viewer")
        else:
            self.setWindowTitle("EML Viewer")

    def _open_file(self) -> None:
        path = dialogs.select_eml_file(self)
        if path is None:
            return
        self.load_email_async(path)

    def load_email(self, path: str | Path) -> None:
        """Synchronously parse and display an email for compatibility callers."""
        if self._email_load_closed:
            return
        self._email_load_request_id += 1
        self._pending_email_load = None
        self._pending_navigation_index = None
        self._pending_navigation_path = None
        self._pending_navigation_active = False
        try:
            parsed_email = self._parser.parse_file(path)
        except Exception as exc:
            self._show_error(tr("error.open_eml.title"), exc)
            return

        self._display_email(parsed_email)
        self._current_email_path = Path(path)
        self.statusBar().showMessage(tr("status.file_opened", source_path=parsed_email.source_path), 5000)
        try:
            self._settings_service.add_recent_file(path)
        except OSError as exc:
            self._show_settings_save_error(exc)
        self._update_recent_files_menu()
        self._update_folder_navigation(path)

    def load_email_async(self, path: str | Path, *, navigation_index: int | None = None) -> None:
        """Queue a UI email load; one parse runs and only the latest pending request is kept."""
        if self._email_load_closed:
            return
        self._pending_navigation_index = navigation_index
        self._pending_navigation_active = navigation_index is not None
        self._pending_navigation_path = Path(path).resolve() if navigation_index is not None else None
        self._email_load_request_id += 1
        request = (self._email_load_request_id, path)
        thread = self._email_load_thread
        # A finished worker still owns this slot until its queued finished event.
        if thread is not None:
            self._pending_email_load = request
            return
        self._start_email_load(*request)

    def _start_email_load(self, request_id: int, path: str | Path) -> None:
        if self._email_load_closed:
            return
        self._welcome_loading.setText(tr("welcome.opening", filename=display_safe_text(Path(path).name)))
        self._welcome_loading.show()
        if self._current_email is None:
            self._content_stack.setCurrentWidget(self._welcome_page)
        self.statusBar().showMessage(
            tr("status.opening", filename=display_safe_text(Path(path).name))
        )
        thread = EmailLoadThread(self._parser, request_id, path)
        self._email_load_thread = thread
        thread.loaded.connect(self._on_email_load_succeeded)
        thread.failed.connect(self._on_email_load_failed)
        thread.finished.connect(self._on_email_load_finished)
        thread.start()

    def _on_email_load_succeeded(self, request_id: int, requested_path: str | Path, email: ParsedEmail) -> None:
        if self._email_load_closed or request_id != self._email_load_request_id:
            return
        self._welcome_loading.hide()
        self._pending_navigation_index = None
        self._pending_navigation_path = None
        self._pending_navigation_active = False
        current_path = Path(email.source_path) if email.source_path is not None else Path(requested_path)
        self._current_email_path = current_path
        self._display_email(email, source_path=current_path)
        self.statusBar().showMessage(tr("status.file_opened", source_path=display_safe_text(current_path)), 5000)
        try:
            self._settings_service.add_recent_file(current_path)
        except OSError as exc:
            self._show_settings_save_error(exc)
        self._update_recent_files_menu()
        self._update_folder_navigation(current_path)

    def _on_email_load_failed(self, request_id: int, error: Exception) -> None:
        if self._email_load_closed or request_id != self._email_load_request_id:
            return
        self._welcome_loading.hide()
        self.statusBar().clearMessage()
        if self._current_email is None:
            self._content_stack.setCurrentWidget(self._welcome_page)
        self._pending_navigation_index = None
        self._pending_navigation_path = None
        self._pending_navigation_active = False
        self._show_error(tr("error.open_eml.title"), error)

    def _on_email_load_finished(self) -> None:
        thread = self.sender()
        if not isinstance(thread, EmailLoadThread):
            return
        if self._email_load_thread is thread:
            self._email_load_thread = None
        thread.deleteLater()
        if self._email_load_closed:
            return
        pending = self._pending_email_load
        self._pending_email_load = None
        if pending is not None:
            self._start_email_load(*pending)

    def _update_folder_navigation(self, current_path: str | Path) -> None:
        try:
            path = Path(current_path).resolve()
            parent = path.parent
            watched = self._folder_watcher.directories()
            watched_normalized = {os.path.normcase(os.path.normpath(str(Path(item).resolve()))) for item in watched}
            parent_normalized = os.path.normcase(os.path.normpath(str(parent)))
            if watched_normalized != {parent_normalized}:
                if watched:
                    self._folder_watcher.removePaths(watched)
                if parent.is_dir():
                    if not self._folder_watcher.addPath(str(parent)):
                        # Unsupported watchers must use fresh scans, not stale cache.
                        self._folder_navigation.invalidate()
            self._folder_emails = list(self._folder_navigation.files(parent))
            try:
                self._current_folder_index = self._folder_emails.index(path)
            except ValueError:
                self._current_folder_index = -1
            if self._pending_navigation_active:
                pending_path = self._pending_navigation_path
                try:
                    self._pending_navigation_index = self._folder_emails.index(pending_path) if pending_path is not None else None
                except ValueError:
                    self._pending_navigation_path = None
                    self._pending_navigation_index = None
                    self._pending_navigation_active = False
                    self._pending_email_load = None
                    self._email_load_request_id += 1
        except Exception:
            self._folder_emails = []
            self._current_folder_index = -1
            if self._pending_navigation_active:
                self._pending_navigation_active = False
                self._pending_navigation_path = None
                self._pending_navigation_index = None
                self._pending_email_load = None
                self._email_load_request_id += 1

        self._update_navigation_actions()

    def _on_folder_changed(self, folder: str) -> None:
        """Invalidate the current listing and reflect filesystem changes."""
        if self._email_load_closed:
            return
        self._folder_navigation.invalidate(folder)
        self._folder_change_timer.start()

    def _refresh_folder_navigation_after_change(self) -> None:
        if self._email_load_closed or self._current_email_path is None:
            return
        self._update_folder_navigation(self._current_email_path)

    def _update_navigation_actions(self) -> None:
        has_prev = self._current_folder_index > 0
        has_next = 0 <= self._current_folder_index < len(self._folder_emails) - 1
        self._prev_email_action.setEnabled(has_prev)
        self._next_email_action.setEnabled(has_next)

    def _navigate_prev_email(self) -> None:
        index = self._navigation_base_index()
        if index > 0:
            target = index - 1
            self.load_email_async(self._folder_emails[target], navigation_index=target)

    def _navigate_next_email(self) -> None:
        index = self._navigation_base_index()
        if 0 <= index < len(self._folder_emails) - 1:
            target = index + 1
            self.load_email_async(self._folder_emails[target], navigation_index=target)

    def _navigation_base_index(self) -> int:
        if not self._pending_navigation_active:
            return self._current_folder_index
        if self._pending_navigation_path is None:
            return -1
        try:
            self._pending_navigation_index = self._folder_emails.index(self._pending_navigation_path)
        except ValueError:
            self._pending_navigation_index = None
            self._pending_navigation_path = None
            return -1
        return self._pending_navigation_index

    def _save_as(self) -> None:
        if self._current_email is None or self._current_email.source_path is None:
            return

        src_path = Path(self._current_email.source_path)
        dest_path_str, _ = QFileDialog.getSaveFileName(
            self,
            tr("dialog.save_as.title"),
            src_path.name,
            tr("dialog.save_as.filter"),
        )
        if not dest_path_str:
            return

        dest_path = Path(dest_path_str)
        try:
            shutil.copy2(src_path, dest_path)
            FileOperationService.apply_mark_of_the_web(dest_path)
            dialogs.show_info(self, tr("dialog.save_as.title"), tr("dialog.save_as.success", path=dest_path.name))
            self.statusBar().showMessage(tr("dialog.save_as.success", path=str(dest_path)), 5000)
        except Exception as exc:
            self._show_error(tr("dialog.save_as.title"), exc)

    def _export_as_pdf(self) -> None:
        if self._current_email is None or self._body_widget.print_busy:
            return

        default_name = "email.pdf"
        if self._current_email.subject:
            safe_subj = self._file_operation_service.sanitize_filename(self._current_email.subject)
            if safe_subj:
                default_name = f"{safe_subj}.pdf"

        dest_path_str, _ = QFileDialog.getSaveFileName(
            self,
            tr("dialog.export_pdf.title"),
            default_name,
            tr("dialog.export_pdf.filter"),
        )
        if not dest_path_str:
            return

        target_path = Path(dest_path_str)
        if target_path.suffix.lower() != ".pdf":
            target_path = target_path.with_suffix(".pdf")

        try:
            try:
                previous_stat = target_path.stat()
                previous_stamp = (previous_stat.st_mtime_ns, previous_stat.st_size)
                existed_before = True
            except FileNotFoundError:
                previous_stamp = None
                existed_before = False
            except OSError:
                previous_stamp = None
                existed_before = True

            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(target_path))

            def _on_pdf_finished(success: bool) -> None:
                if self._email_load_closed:
                    return
                if success:
                    try:
                        output_stat = target_path.stat()
                        output_stamp = (output_stat.st_mtime_ns, output_stat.st_size)
                        output_valid = output_stat.st_size > 0 and (
                            not existed_before
                            or (previous_stamp is not None and output_stamp != previous_stamp)
                        )
                    except OSError:
                        output_valid = False
                    if not output_valid:
                        self._show_error(
                            tr("dialog.export_pdf.title"),
                            RuntimeError("PDF export did not create a new non-empty file"),
                        )
                        return
                    dialogs.show_info(self, tr("dialog.export_pdf.title"), tr("dialog.export_pdf.success", path=target_path.name))
                    self.statusBar().showMessage(tr("dialog.export_pdf.success", path=str(target_path)), 5000)
                else:
                    self._show_error(tr("dialog.export_pdf.title"), RuntimeError("PDF export failed"))

            self._body_widget.print_content(printer, on_finished=_on_pdf_finished)
        except Exception as exc:
            self._show_error(tr("dialog.export_pdf.title"), exc)

    def _view_message_source(self) -> None:
        if self._current_email is None:
            return

        source_text = ""
        if self._current_email.source_path and Path(self._current_email.source_path).suffix.lower() == ".eml":
            try:
                raw_bytes = Path(self._current_email.source_path).read_bytes()
                from eml_viewer.services.eml_parser import _safe_decode
                source_text = _safe_decode(raw_bytes, "utf-8")
            except Exception:
                pass

        if not source_text:
            headers = self._current_email.raw_headers
            body = self._current_email.plain_body or self._current_email.html_body
            source_text = f"{headers}\n\n{body}" if headers else body

        dialogs.show_source_dialog(self, tr("dialog.source.title"), source_text)

    def _display_email(self, email: ParsedEmail, *, source_path: str | Path | None = None) -> None:
        self._current_email = email
        self._subject_edit.setText(display_safe_text(email.subject))
        self._sender_edit.setText(display_safe_text(email.sender))
        self._to_edit.setText(display_safe_text(email.recipients))
        self._cc_edit.setText(display_safe_text(email.cc))
        self._date_edit.setText(display_safe_text(email.date))
        file_path = Path(source_path) if source_path is not None else (Path(email.source_path) if email.source_path else None)
        self._current_file_label.setText(display_safe_text(file_path or ""))
        self._current_file_label.setTextFormat(Qt.TextFormat.PlainText)
        self._current_file_label.setToolTip(safe_tooltip(file_path or ""))
        subject = display_safe_text(email.subject or tr("app.untitled_subject"))
        self._subject_summary.setText(subject)
        self._subject_summary.setToolTip(safe_tooltip(email.subject or tr("app.untitled_subject")))
        sender = display_safe_text(email.sender or tr("metadata.unknown"))
        date = display_safe_text(email.date or tr("metadata.unknown"))
        filename = file_path.name if file_path else tr("metadata.unknown")
        self._summary_meta.setText(f"{sender} · {date} · {display_safe_text(filename)}")
        self._summary_meta.setToolTip(safe_tooltip(f"{email.sender} · {email.date} · {file_path or ''}"))
        self._set_details_visible(self._details_toggle.isChecked())
        cc_label_item = self._metadata_group.layout().labelForField(self._cc_edit)
        if cc_label_item is not None:
            cc_label_item.setVisible(bool(email.cc))
        self._cc_edit.setVisible(bool(email.cc))
        self._forward_button.setEnabled(file_path is not None)
        self._body_widget.set_email(email)
        self._attachment_panel.set_attachments(email.attachments)
        self._content_stack.setCurrentWidget(self._message_page)
        self._update_print_actions()
        self._update_window_title()

    def _set_details_visible(self, visible: bool) -> None:
        self._metadata_group.setVisible(visible and self._current_email is not None)
        self._metadata_scroll_area.setVisible(visible and self._current_email is not None)
        self._details_toggle.setArrowType(
            Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow
        )

    def _show_summary_copy_menu(self, point) -> None:
        email = self._current_email
        if email is None:
            return
        menu = QMenu(self)
        copy_subject = menu.addAction(tr("copy.subject"))
        copy_subject.triggered.connect(lambda: self._copy_to_clipboard(email.subject))
        copy_sender = menu.addAction(tr("copy.sender"))
        copy_sender.triggered.connect(lambda: self._copy_to_clipboard(email.sender))
        menu.exec(self._subject_summary.mapToGlobal(point))

    def _update_print_actions(self, _busy: bool | None = None) -> None:
        can_print = self._current_email is not None and not self._body_widget.print_busy
        self._print_action.setEnabled(can_print)
        self._export_pdf_action.setEnabled(can_print)
        self._open_browser_action.setEnabled(can_print)
        self._save_as_action.setEnabled(
            self._current_email is not None and self._current_email.source_path is not None
        )

    def _copy_to_clipboard(self, text: str) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
            self.statusBar().showMessage(tr("status.copied"), 3000)

    def _open_in_browser(self) -> None:
        if self._current_email is None or self._body_widget.print_busy:
            return

        html_content = self._body_widget.current_prepared_html()
        if not html_content.strip():
            return

        clean_html = re.sub(
            r'<meta[^>]+charset=["\']?[^"\'>]+["\']?[^>]*>',
            '<meta charset="utf-8">',
            html_content,
            flags=re.IGNORECASE,
        )
        csp_meta = '<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="script-src \'none\';">'
        if re.search(r"<head>", clean_html, re.IGNORECASE):
            clean_html = re.sub(r"<head>", f"<head>{csp_meta}", clean_html, count=1, flags=re.IGNORECASE)
        else:
            clean_html = f"<head>{csp_meta}</head>{clean_html}"

        preview_file = self._session_temp_dir / "preview.html"
        try:
            preview_file.write_text(clean_html, encoding="utf-8")
            if hasattr(os, "startfile"):
                os.startfile(str(preview_file))
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(preview_file)))
        except Exception as exc:
            self._show_error(tr("error.open_browser.title"), exc)

    def _open_new_window(self) -> None:
        if self._window_manager is not None and hasattr(self._window_manager, "create_window"):
            self._window_manager.create_window()
        else:
            win = MainWindow(
                parser=self._parser,
                attachment_service=self._attachment_service,
                settings_service=self._settings_service,
                file_operation_service=self._file_operation_service,
                forward_service=self._forward_service,
                update_service=self._update_service,
                auto_check_update=False,
            )
            win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self._child_windows.append(win)
            win.destroyed.connect(lambda checked=False, w=win: self._child_windows.remove(w) if w in self._child_windows else None)
            win.show()

    def _print_current_message(self) -> None:
        if self._current_email is None or self._body_widget.print_busy:
            return

        try:
            from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        except ImportError:
            return

        try:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            dialog = QPrintDialog(printer, self)
            if dialog.exec() != QPrintDialog.DialogCode.Accepted:
                return

            self._body_widget.print_content(printer)
        except Exception as exc:
            self._show_error(tr("print.failed.title"), exc)

    def _open_settings(self) -> None:
        settings = self._settings_service.load_settings()
        dialog = SettingsDialog(settings, self, settings_directory=self._settings_service.settings_path.parent)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return

        new_settings = replace(
            settings,
            language=dialog.language,
            theme=dialog.theme,
            auto_load_remote_images=dialog.auto_load_remote_images,
            startup_with_windows=dialog.startup_with_windows,
            minimize_to_tray_on_close=dialog.minimize_to_tray_on_close,
            smtp_host=dialog.smtp_host,
            smtp_sender=dialog.smtp_sender,
            smtp_port=dialog.smtp_port,
        )
        language_changed = new_settings.language != settings.language
        applied_settings = new_settings
        try:
            if self._window_manager is not None and hasattr(self._window_manager, "broadcast_settings"):
                applied_settings = self._window_manager.broadcast_settings(new_settings) or new_settings
            else:
                self._settings_service.save_settings(new_settings)
        except OSError as exc:
            self._show_settings_save_error(exc)
            return
        if self._window_manager is None or not hasattr(self._window_manager, "broadcast_settings"):
            from eml_viewer.gui.i18n import set_language
            set_language(new_settings.language)
            apply_theme(QApplication.instance(), new_settings.theme)
            self.apply_settings(new_settings)
        if language_changed:
            self._retranslate_ui()
            dialogs.show_info(self, tr("settings.title"), tr("settings.language_applied"))
        if new_settings.startup_with_windows != applied_settings.startup_with_windows:
            dialogs.show_warning(self, tr("settings.title"), tr("settings.startup_sync_failed"))
        self.statusBar().showMessage(tr("settings.saved"), 5000)

    def _forward_current_email(self) -> None:
        if self._current_email is None:
            dialogs.show_error(self, tr("forward.error.title"), tr("forward.error.no_email"))
            return

        settings = self._settings_service.load_settings()
        selection = dialogs.request_forward_recipients(self, settings.recent_recipients)
        if selection is None:
            return

        try:
            recipient = self._forward_service.forward_email(
                self._current_email,
                settings,
                selection.recipients,
            )
        except ForwardConfigError as exc:
            message_box = QMessageBox(self)
            message_box.setIcon(QMessageBox.Icon.Warning)
            message_box.setWindowTitle(tr("forward.config_required.title"))
            message_box.setText(tr("forward.config_required.body", error=exc))
            settings_button = message_box.addButton(tr("menu.settings"), QMessageBox.ButtonRole.AcceptRole)
            message_box.addButton(tr("settings.cancel"), QMessageBox.ButtonRole.RejectRole)
            message_box.exec()
            if message_box.clickedButton() == settings_button:
                self._open_settings()
            return
        except Exception as exc:
            self._show_error(tr("forward.error.title"), exc)
            return

        try:
            self._settings_service.save_recent_recipients((recipient, *selection.recent_recipients))
        except OSError as exc:
            self._show_settings_save_error(exc)
        dialogs.show_info(
            self,
            tr("forward.success.title"),
            tr("forward.completed", recipient=recipient),
        )
        self.statusBar().showMessage(tr("forward.completed.status"), 5000)

    def _save_attachments(self, attachments: list[AttachmentInfo]) -> None:
        if self._current_email is None or self._current_email.source_path is None:
            dialogs.show_error(self, tr("error.attachment_save.title"), tr("forward.error.no_email"))
            return
        if not attachments:
            return

        if len(attachments) == 1:
            self._save_single_attachment(attachments[0])
            return

        dangerous_items = [
            att.filename for att in attachments
            if is_dangerous_extension(self._file_operation_service.sanitize_filename(att.filename))
        ]
        if dangerous_items:
            names_summary = ", ".join(display_safe_text(name) for name in dangerous_items[:3])
            names_summary += "..." if len(dangerous_items) > 3 else ""
            confirmed = dialogs.ask_warning_yes_no(
                self,
                tr("dialog.save_dangerous.title"),
                tr("dialog.save_dangerous.body", filename=names_summary),
            )
            if not confirmed:
                self.statusBar().showMessage(tr("status.attachment_save_canceled"), 5000)
                return

        destination_dir = dialogs.select_attachment_directory(self)
        if destination_dir is None:
            return

        previews = self._attachment_service.create_bulk_save_preview(attachments, destination_dir)
        overwrite_count = sum(1 for preview in previews if preview.will_overwrite)
        preview_lines = "\n".join(f"- {preview.source_label} -> {preview.destination.name}" for preview in previews)
        overwrite_text = (
            tr("attachment.bulk_overwrite", count=overwrite_count)
            if overwrite_count
            else tr("attachment.bulk_all_new")
        )
        if not dialogs.ask_execute_file_operation(
            self,
            tr("dialog.save_attachment.title"),
            tr(
                "attachment.bulk_preview",
                destination_dir=destination_dir,
                preview_lines=preview_lines,
                overwrite_text=overwrite_text,
            ),
        ):
            self.statusBar().showMessage(tr("status.attachment_save_canceled"), 5000)
            return

        try:
            results = self._attachment_service.save_attachments(
                email_path=self._current_email.source_path,
                attachments=attachments,
                destination_dir=destination_dir,
                overwrite=bool(overwrite_count),
            )
        except Exception as exc:
            self._show_error(tr("error.attachment_save.title"), exc)
            return

        dialogs.show_info(
            self,
            tr("dialog.save_attachment.title"),
            tr("attachment.saved_many", count=len(results), destination_dir=destination_dir),
        )
        self.statusBar().showMessage(
            tr("attachment.saved_many.status", count=len(results), destination_dir=destination_dir), 5000
        )

    def _save_single_attachment(self, attachment: AttachmentInfo) -> None:
        if self._current_email is None or self._current_email.source_path is None:
            dialogs.show_error(self, tr("error.attachment_save.title"), tr("forward.error.no_email"))
            return

        safe_filename = self._file_operation_service.sanitize_filename(attachment.filename)
        if is_dangerous_extension(safe_filename):
            confirmed = dialogs.ask_warning_yes_no(
                self,
                tr("dialog.save_dangerous.title"),
                tr("dialog.save_dangerous.body", filename=display_safe_text(safe_filename)),
            )
            if not confirmed:
                self.statusBar().showMessage(tr("status.attachment_save_canceled"), 5000)
                return

        destination = dialogs.select_attachment_destination(self, safe_filename)
        if destination is None:
            return

        preview = self._attachment_service.create_save_preview(attachment, destination)
        if not dialogs.ask_execute_file_operation(self, tr("dialog.save_attachment.title"), preview.message):
            self.statusBar().showMessage(tr("status.attachment_save_canceled"), 5000)
            return
        overwrite = preview.will_overwrite

        try:
            saved_path = self._attachment_service.save_attachment(
                email_path=self._current_email.source_path,
                attachment_index=attachment.index,
                destination_path=preview.destination,
                overwrite=overwrite,
            )
        except Exception as exc:
            self._show_error(tr("error.attachment_save.title"), exc)
            return

        dialogs.show_info(
            self,
            tr("dialog.save_attachment.title"),
            tr("attachment.saved_one", saved_path=saved_path),
        )
        self.statusBar().showMessage(tr("attachment.saved_one.status", saved_path=saved_path), 5000)

    def _open_attachments(self, attachments: list[AttachmentInfo]) -> None:
        if self._current_email is None or self._current_email.source_path is None:
            dialogs.show_error(self, tr("error.attachment_open.title"), tr("forward.error.no_email"))
            return

        if len(attachments) > 5:
            confirmed = dialogs.ask_warning_yes_no(
                self,
                tr("dialog.open_many_attachments.title"),
                tr("dialog.open_many_attachments.body", count=len(attachments)),
            )
            if not confirmed:
                return

        failed_files: list[str] = []
        for attachment in attachments:
            safe_filename = self._file_operation_service.sanitize_filename(attachment.filename)
            if is_dangerous_extension(safe_filename):
                confirmed = dialogs.ask_warning_yes_no(
                    self,
                    tr("dialog.open_dangerous.title"),
                    tr("dialog.open_dangerous.body", filename=display_safe_text(safe_filename)),
                )
                if not confirmed:
                    continue

            # 동일 파일명 충돌 방지를 위해 첨부파일 인덱스별 전용 하위 디렉터리 사용
            attachment_dir = self._session_temp_dir / str(attachment.index)
            attachment_dir.mkdir(parents=True, exist_ok=True)
            dest_file = attachment_dir / safe_filename

            try:
                self._attachment_service.save_attachment(
                    email_path=self._current_email.source_path,
                    attachment_index=attachment.index,
                    destination_path=dest_file,
                    overwrite=True,
                )
                if hasattr(os, "startfile"):
                    os.startfile(str(dest_file))
                else:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(dest_file)))
            except Exception as exc:
                failed_files.append(
                    f"{_safe_message_lines(attachment.filename)}: {_safe_message_lines(exc)}"
                )

        if failed_files:
            dialogs.show_error(
                self,
                tr("error.attachment_open.title"),
                "\n".join(failed_files),
            )

    def _restore_window_geometry(self) -> None:
        settings = self._settings_service.load_settings()
        saved_geometry = QRect(
            settings.window_x,
            settings.window_y,
            settings.window_width,
            settings.window_height,
        )
        screens = QApplication.screens()

        if self._geometry_is_visible(saved_geometry, screens):
            self.setGeometry(saved_geometry)
            return

        primary_screen = QApplication.primaryScreen()
        if primary_screen is None:
            self.setGeometry(saved_geometry)
            return

        available_geometry = primary_screen.availableGeometry()
        width = min(max(saved_geometry.width(), 1), available_geometry.width())
        height = min(max(saved_geometry.height(), 1), available_geometry.height())
        self.setGeometry(
            available_geometry.x() + (available_geometry.width() - width) // 2,
            available_geometry.y() + (available_geometry.height() - height) // 2,
            width,
            height,
        )

    @staticmethod
    def _geometry_is_visible(geometry: QRect, screens: list) -> bool:
        minimum_visible_size = 100
        for screen in screens:
            visible_area = geometry.intersected(screen.availableGeometry())
            if (
                visible_area.width() >= minimum_visible_size
                and visible_area.height() >= minimum_visible_size
            ):
                return True
        return False

    def _on_exit_action_triggered(self) -> None:
        """파일 메뉴의 '종료' 액션 트리거 시 트레이 상주 여부와 무관하게 애플리케이션을 완전히 종료합니다."""
        if self._window_manager is not None and hasattr(self._window_manager, "force_quit"):
            self._window_manager.force_quit()
        else:
            app = QApplication.instance()
            if app is not None:
                app.quit()
            else:
                self.close()

    def closeEvent(self, event) -> None:
        if self._close_event_started:
            super().closeEvent(event)
            return
        self._close_event_started = True
        self._email_load_closed = True
        self._pending_email_load = None
        self._pending_navigation_index = None
        self._pending_navigation_path = None
        self._pending_navigation_active = False
        self._folder_change_timer.stop()
        watched = self._folder_watcher.directories()
        if watched:
            self._folder_watcher.removePaths(watched)
        if self._window_manager is None and self._body_widget.print_busy:
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            _orphaned_print_windows.add(self)
            self._body_widget.print_busy_changed.connect(self._on_standalone_print_busy_changed)
        if self._email_load_thread is not None and self._email_load_thread.isRunning():
            thread = self._email_load_thread
            try:
                thread.disconnect(self)
            except (RuntimeError, TypeError):
                pass
            if self._window_manager is not None and hasattr(self._window_manager, "retain_thread"):
                self._window_manager.retain_thread(thread)
            else:
                # app.py wires managed shutdown to WindowManager; standalone windows retain workers until completion.
                _orphaned_email_threads.add(thread)
                thread.finished.connect(lambda t=thread: _release_orphaned_email_thread(t))
                app = QApplication.instance()
                if app is not None and not app.property("emlViewerOrphanThreadCleanupConnected"):
                    app.aboutToQuit.connect(_wait_for_orphaned_email_threads)
                    app.setProperty("emlViewerOrphanThreadCleanupConnected", True)
                # The worker can finish between the initial running check and signal connection.
                if thread.isFinished():
                    _release_orphaned_email_thread(thread)
            self._email_load_thread = None

        if self._update_check_thread is not None and self._update_check_thread.isRunning():
            thread = self._update_check_thread
            try:
                thread.disconnect(self)
            except (RuntimeError, TypeError):
                pass
            if self._window_manager is not None and hasattr(self._window_manager, "retain_thread"):
                self._window_manager.retain_thread(thread)
            else:
                thread.wait()
            self._update_check_thread = None

        if self._download_thread is not None and self._download_thread.isRunning():
            thread = self._download_thread
            thread.cancel()
            try:
                thread.disconnect(self)
            except (RuntimeError, TypeError):
                pass
            if self._window_manager is not None and hasattr(self._window_manager, "retain_thread"):
                self._window_manager.retain_thread(thread)
            else:
                thread.wait()
            self._download_thread = None

        if self._window_manager is not None and hasattr(self._window_manager, "unregister_window"):
            self._window_manager.unregister_window(self)
        try:
            geometry = self.geometry()
            self._settings_service.save_window_geometry(
                x=geometry.x(),
                y=geometry.y(),
                width=geometry.width(),
                height=geometry.height(),
            )
        except OSError as exc:
            logger.warning("Window geometry could not be saved: %s", exc)
        try:
            if hasattr(self, "_cleanup_session_callback"):
                atexit.unregister(self._cleanup_session_callback)
        except Exception:
            pass
        try:
            if hasattr(self, "_session_temp_dir") and self._session_temp_dir.exists():
                shutil.rmtree(str(self._session_temp_dir), ignore_errors=True)
        except Exception:
            pass
        super().closeEvent(event)

    def _on_standalone_print_busy_changed(self, busy: bool) -> None:
        if not self._email_load_closed or busy:
            return
        try:
            self._body_widget.print_busy_changed.disconnect(self._on_standalone_print_busy_changed)
        except (RuntimeError, TypeError):
            pass
        _orphaned_print_windows.discard(self)
        self.deleteLater()

    def _show_error(self, title: str, error: Exception) -> None:
        dialogs.show_error(self, title, _safe_message_lines(ErrorService.to_user_message(error)))

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.DevicePixelRatioChange):
            action = getattr(self, "_print_action", None)
            if action is not None:
                action.setIcon(
                    printer_icon(self.palette(), device_pixel_ratio=self.devicePixelRatioF())
                )

    def _show_settings_save_error(self, error: OSError) -> None:
        logger.warning("Settings could not be saved: %s", error)
        dialogs.show_error(self, tr("settings.title"), tr("settings.save_failed"))
        self.statusBar().showMessage(tr("settings.save_failed"), 5000)

    def _check_for_updates(self) -> None:
        self.statusBar().showMessage(tr("update.checking"))
        if self._update_check_thread is not None and self._update_check_thread.isRunning():
            return
        self._update_check_thread = UpdateCheckThread(self._update_service)
        self._update_check_thread.check_finished.connect(self._on_manual_update_check_finished)
        self._update_check_thread.failed.connect(self._on_manual_update_check_failed)
        self._update_check_thread.start()

    def _on_manual_update_check_failed(self, message: str) -> None:
        dialogs.show_error(self, tr("update.check.failed.title"), message)
        self.statusBar().showMessage(tr("update.check.failed.status"), 5000)

    def _on_manual_update_check_finished(self, result: UpdateCheckResult) -> None:
        if not result.update_available:
            dialogs.show_info(
                self,
                tr("update.current.title"),
                tr("update.current.body", current_version=result.current_version),
            )
            self.statusBar().showMessage(tr("update.current.status"), 5000)
            return

        self._show_update_banner(result)
        message = tr(
            "update.available.body",
            current_version=result.current_version,
            latest_version=result.latest_version,
        )
        answer = QMessageBox.question(
            self,
            tr("update.available.title"),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes and result.download_url:
            if result.download_url.lower().endswith(".exe"):
                self._start_update_download(result)
            else:
                QDesktopServices.openUrl(QUrl(result.download_url))
                self.statusBar().showMessage(tr("update.check.done"), 5000)
        else:
            self.statusBar().showMessage(tr("update.check.done"), 5000)

    def _clear_recent_files(self) -> None:
        current = self._settings_service.load_settings()
        from dataclasses import replace as _replace
        try:
            self._settings_service.save_settings(_replace(current, recent_files=()))
        except OSError as exc:
            self._show_settings_save_error(exc)
            return
        self._update_recent_files_menu()
        self.statusBar().showMessage(tr("status.recent_files_cleared"), 5000)

    def _start_background_update_check(self) -> None:
        if self._update_check_thread is not None and self._update_check_thread.isRunning():
            return
        self._update_check_thread = UpdateCheckThread(self._update_service)
        self._update_check_thread.check_finished.connect(self._on_background_update_check_finished)
        self._update_check_thread.failed.connect(lambda _message: None)
        self._update_check_thread.start()

    def _on_background_update_check_finished(self, result: UpdateCheckResult) -> None:
        if result.update_available:
            self._show_update_banner(result)

    def _show_update_banner(self, result: UpdateCheckResult) -> None:
        self._available_update_result = result
        self._set_update_banner_text(result)
        self._update_banner.setVisible(True)

    def _set_update_banner_text(self, result: UpdateCheckResult) -> None:
        self._update_banner_label.setText(
            tr(
                "update.banner",
                latest_version=result.latest_version,
                current_version=result.current_version,
            )
        )

    def _download_available_update(self) -> None:
        result = self._available_update_result
        if result is None:
            return
        if result.download_url and result.download_url.lower().endswith(".exe"):
            self._start_update_download(result)
            return
        if result.download_url:
            QDesktopServices.openUrl(QUrl(result.download_url))
        else:
            QDesktopServices.openUrl(QUrl(result.release_url))
        self.statusBar().showMessage(tr("update.opened_page"), 5000)

    def _start_update_download(self, result: UpdateCheckResult) -> None:
        if not result.download_url:
            return

        dest_path = str(self._update_service.installer_cache_path(result))
        if self._update_service.has_valid_cached_installer(result):
            self._on_download_finished(dest_path)
            return

        self._progress_dialog = QProgressDialog(
            tr("update.downloading_installer"),
            tr("settings.cancel"),
            0,
            100,
            self,
        )
        self._progress_dialog.setWindowTitle(tr("update.download.title"))
        self._progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress_dialog.setAutoClose(False)
        self._progress_dialog.setAutoReset(False)
        self._progress_dialog.setValue(0)

        self._download_thread = DownloadThread(self._update_service, result.download_url, dest_path)
        self._download_thread.progress.connect(self._on_download_progress)
        self._download_thread.download_finished.connect(self._on_download_finished)
        self._download_thread.failed.connect(self._on_download_failed)

        self._progress_dialog.canceled.connect(self._download_thread.cancel)
        self._progress_dialog.show()

        self._download_thread.start()
        self.statusBar().showMessage(tr("update.download.in_progress"), 0)

    def _on_download_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            val = int(downloaded * 100 / total)
            self._progress_dialog.setValue(val)
            downloaded_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            self._progress_dialog.setLabelText(
                tr("update.download.label_total", downloaded_mb=downloaded_mb, total_mb=total_mb)
            )
        else:
            downloaded_mb = downloaded / (1024 * 1024)
            self._progress_dialog.setLabelText(
                tr("update.download.label", downloaded_mb=downloaded_mb)
            )

    def _on_download_finished(self, dest_path: str) -> None:
        self._progress_dialog.close()
        self.statusBar().showMessage(tr("update.download_complete"), 5000)

        # 방어적 코드: 다운로드된 파일 존재 여부 및 유효성(크기) 검증
        if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
            dialogs.show_error(
                self,
                tr("update.installer_validation_failed.title"),
                tr("update.installer_validation_failed.body")
            )
            return

        dialogs.show_info(
            self,
            tr("update.installer_ready.title"),
            tr("update.installer_ready.body")
        )


        try:
            os.startfile(dest_path)
        except Exception as exc:
            dialogs.show_error(
                self,
                tr("update.installer_execute_failed.title"),
                tr("update.installer_execute_failed.body", error=exc)
            )
            return

        self.close()
        if self._window_manager is not None and hasattr(self._window_manager, "force_quit"):
            self._window_manager.force_quit()
        else:
            app = QApplication.instance()
            if app is not None:
                app.quit()

    def _on_download_failed(self, error_msg: str) -> None:
        self._progress_dialog.close()
        if "다운로드가 취소되었습니다" in error_msg or "download canceled" in error_msg.lower():
            self.statusBar().showMessage(tr("update.download.canceled"), 5000)
            return

        dialogs.show_error(
            self,
            tr("update.download.failed.title"),
            tr("update.download.failed.body", error=error_msg)
        )
        self.statusBar().showMessage(tr("update.download.failed.status"), 5000)
