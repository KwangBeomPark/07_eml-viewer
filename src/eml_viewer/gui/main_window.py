from __future__ import annotations

import atexit
import os
import re
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QRect, Qt, QUrl, QThread, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
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
from eml_viewer.models.attachment_data import AttachmentInfo
from eml_viewer.models.email_data import ParsedEmail
from eml_viewer.services.attachment_policy import DANGEROUS_EXTENSIONS, is_dangerous_extension
from eml_viewer.services.attachment_service import AttachmentService
from eml_viewer.services.eml_parser import EmlParser
from eml_viewer.services.error_service import ErrorService
from eml_viewer.services.file_operation_service import FileOperationService
from eml_viewer.services.forward_service import ForwardConfigError, ForwardService
from eml_viewer.services.settings_service import SettingsService
from eml_viewer.services.update_service import UpdateCheckError, UpdateCheckResult, UpdateService


class DownloadThread(QThread):
    progress = Signal(int, int)  # downloaded, total
    finished = Signal(str)
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
                self.finished.emit(self._dest_path)
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
        self._current_folder_index: int = -1
        self._download_thread: DownloadThread | None = None
        self._update_check_thread: UpdateCheckThread | None = None
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

        self.setWindowTitle("EML Viewer")
        self._build_actions()
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
        self.load_email(valid_paths[0])

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
                self._child_windows.append(win)
                win.destroyed.connect(lambda checked=False, w=win: self._child_windows.remove(w) if w in self._child_windows else None)
                win.load_email(remaining_path)
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
        self._prev_email_action.setShortcut("Alt+Left")
        self._prev_email_action.triggered.connect(self._navigate_prev_email)
        self._prev_email_action.setEnabled(False)

        self._next_email_action = QAction(self)
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
        self._toolbar.setMovable(False)
        self._toolbar.addAction(self._new_window_action)
        self._toolbar.addAction(self._open_action)
        self._toolbar.addAction(self._save_as_action)
        self._toolbar.addAction(self._export_pdf_action)
        self._toolbar.addSeparator()
        self._toolbar.addAction(self._prev_email_action)
        self._toolbar.addAction(self._next_email_action)
        self._toolbar.addSeparator()
        self._toolbar.addAction(self._open_browser_action)
        self._toolbar.addAction(self._print_action)

    def _build_ui(self) -> None:
        self._open_button = QPushButton(self)
        self._open_button.clicked.connect(self._open_file)
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

        top_layout = QHBoxLayout()
        top_layout.addWidget(self._open_button)
        top_layout.addWidget(self._forward_button)
        top_layout.addWidget(self._current_file_label, stretch=1)

        self._metadata_group = QGroupBox(self)
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

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.addWidget(self._body_widget)
        splitter.addWidget(self._attachment_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        content_layout = QVBoxLayout()
        content_layout.addWidget(self._update_banner)
        content_layout.addLayout(top_layout)
        content_layout.addWidget(self._metadata_group)
        content_layout.addWidget(splitter, stretch=1)


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
        self._new_window_action.setText(tr("action.new_window"))
        self._open_action.setText(tr("button.open_eml"))
        self._save_as_action.setText(tr("action.save_as"))
        self._export_pdf_action.setText(tr("action.export_pdf"))
        self._open_browser_action.setText(tr("button.open_browser"))
        self._print_action.setText(tr("action.print"))
        self._view_source_action.setText(tr("action.view_source"))
        self._prev_email_action.setText(tr("action.prev_email"))
        self._next_email_action.setText(tr("action.next_email"))
        self._settings_action.setText(tr("menu.settings"))
        self._exit_action.setText(tr("menu.exit"))
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
        self._open_button.setText(tr("button.open_eml"))
        self._forward_button.setText(tr("forward.current"))
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
            action = self._recent_files_menu.addAction(display_name)
            action.setToolTip(file_path)
            action.setStatusTip(file_path)
            action.triggered.connect(lambda checked=False, p=file_path: self.load_email(p))

        self._recent_files_menu.addSeparator()
        clear_action = self._recent_files_menu.addAction(tr("menu.recent_clear"))
        clear_action.triggered.connect(self._clear_recent_files)

    def _update_window_title(self) -> None:
        if self._current_email is not None:
            raw_subject = self._current_email.subject or ""
            subject = re.sub(r"[\r\n\t]+", " ", raw_subject).strip()
            display_subject = subject if subject else tr("app.untitled_subject")
            self.setWindowTitle(f"{display_subject} - EML Viewer")
        else:
            self.setWindowTitle("EML Viewer")

    def _open_file(self) -> None:
        path = dialogs.select_eml_file(self)
        if path is None:
            return
        self.load_email(path)

    def load_email(self, path: str | Path) -> None:
        try:
            parsed_email = self._parser.parse_file(path)
        except Exception as exc:
            self._show_error(tr("error.open_eml.title"), exc)
            return

        self._display_email(parsed_email)
        self.statusBar().showMessage(tr("status.file_opened", source_path=parsed_email.source_path), 5000)
        self._settings_service.add_recent_file(path)
        self._update_recent_files_menu()
        self._update_folder_navigation(path)

    def _update_folder_navigation(self, current_path: str | Path) -> None:
        try:
            path = Path(current_path).resolve()
            parent = path.parent
            exts = {".eml", ".msg"}
            files = [p for p in parent.iterdir() if p.is_file() and p.suffix.lower() in exts]
            files.sort(key=lambda p: p.name.lower())
            self._folder_emails = files
            try:
                self._current_folder_index = self._folder_emails.index(path)
            except ValueError:
                self._current_folder_index = -1
        except Exception:
            self._folder_emails = []
            self._current_folder_index = -1

        self._update_navigation_actions()

    def _update_navigation_actions(self) -> None:
        has_prev = self._current_folder_index > 0
        has_next = 0 <= self._current_folder_index < len(self._folder_emails) - 1
        self._prev_email_action.setEnabled(has_prev)
        self._next_email_action.setEnabled(has_next)

    def _navigate_prev_email(self) -> None:
        if self._current_folder_index > 0:
            prev_file = self._folder_emails[self._current_folder_index - 1]
            self.load_email(prev_file)

    def _navigate_next_email(self) -> None:
        if 0 <= self._current_folder_index < len(self._folder_emails) - 1:
            next_file = self._folder_emails[self._current_folder_index + 1]
            self.load_email(next_file)

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
        if self._current_email is None:
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
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(target_path))

            def _on_pdf_finished(success: bool) -> None:
                if success:
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

    def _display_email(self, email: ParsedEmail) -> None:
        self._current_email = email
        self._subject_edit.setText(email.subject)
        self._sender_edit.setText(email.sender)
        self._to_edit.setText(email.recipients)
        self._cc_edit.setText(email.cc)
        self._date_edit.setText(email.date)
        self._current_file_label.setText(str(email.source_path or ""))
        self._forward_button.setEnabled(email.source_path is not None)
        self._body_widget.set_email(email)
        self._attachment_panel.set_attachments(email.attachments)
        self._update_window_title()

    def _copy_to_clipboard(self, text: str) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
            self.statusBar().showMessage(tr("status.copied"), 3000)

    def _open_in_browser(self) -> None:
        if self._current_email is None:
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
            self._child_windows.append(win)
            win.destroyed.connect(lambda checked=False, w=win: self._child_windows.remove(w) if w in self._child_windows else None)
            win.show()

    def _print_current_message(self) -> None:
        if self._current_email is None:
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
        dialog = SettingsDialog(settings, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return

        new_settings = replace(
            settings,
            language=dialog.language,
            theme=dialog.theme,
            auto_load_remote_images=dialog.auto_load_remote_images,
            smtp_host=dialog.smtp_host,
            smtp_sender=dialog.smtp_sender,
            smtp_port=dialog.smtp_port,
        )
        language_changed = new_settings.language != settings.language
        if self._window_manager is not None and hasattr(self._window_manager, "broadcast_settings"):
            self._window_manager.broadcast_settings(new_settings)
        else:
            self._settings_service.save_settings(new_settings)
            from eml_viewer.gui.i18n import set_language
            set_language(new_settings.language)
            apply_theme(QApplication.instance(), new_settings.theme)
            self.apply_settings(new_settings)
        if language_changed:
            self._retranslate_ui()
            dialogs.show_info(self, tr("settings.title"), tr("settings.language_applied"))
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

        self._settings_service.save_recent_recipients((recipient, *selection.recent_recipients))
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
            names_summary = ", ".join(dangerous_items[:3]) + ("..." if len(dangerous_items) > 3 else "")
            reply = QMessageBox.warning(
                self,
                tr("dialog.save_dangerous.title"),
                tr("dialog.save_dangerous.body", filename=names_summary),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
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
            reply = QMessageBox.warning(
                self,
                tr("dialog.save_dangerous.title"),
                tr("dialog.save_dangerous.body", filename=safe_filename),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
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

        failed_files: list[str] = []
        for attachment in attachments:
            safe_filename = self._file_operation_service.sanitize_filename(attachment.filename)
            ext = Path(safe_filename).suffix.lower()
            if ext in DANGEROUS_EXTENSIONS:
                reply = QMessageBox.warning(
                    self,
                    tr("dialog.open_dangerous.title"),
                    tr("dialog.open_dangerous.body", filename=safe_filename),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
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
                failed_files.append(f"{attachment.filename}: {exc}")

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

    def closeEvent(self, event) -> None:
        if self._window_manager is not None and hasattr(self._window_manager, "unregister_window"):
            self._window_manager.unregister_window(self)
        if self._update_check_thread is not None and self._update_check_thread.isRunning():
            self._update_check_thread.wait(1000)
        if self._download_thread is not None and self._download_thread.isRunning():
            self._download_thread.cancel()
            self._download_thread.wait()
        try:
            geometry = self.geometry()
            self._settings_service.save_window_geometry(
                x=geometry.x(),
                y=geometry.y(),
                width=geometry.width(),
                height=geometry.height(),
            )
        except Exception:
            pass
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

    def _show_error(self, title: str, error: Exception) -> None:
        dialogs.show_error(self, title, ErrorService.to_user_message(error))

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
        self._settings_service.save_settings(_replace(current, recent_files=()))
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
        self._download_thread.finished.connect(self._on_download_finished)
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
