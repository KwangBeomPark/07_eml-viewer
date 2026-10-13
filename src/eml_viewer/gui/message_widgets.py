from __future__ import annotations

import html
import logging
import mimetypes
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from eml_viewer.gui.search_bar import SearchBarWidget

QWebEnginePage = None
QWebEngineProfile = None
QWebEngineSettings = None
QWebEngineUrlRequestInterceptor = None
QWebEngineView = None
ZoomWebEngineView = None
MailWebEnginePage = None
RemoteContentInterceptor = None
_WEBENGINE_IMPORT_ATTEMPTED = False

from eml_viewer.models.email_data import ParsedEmail
from eml_viewer.gui.i18n import tr


_LOGGER = logging.getLogger(__name__)
_TRANSPARENT_IMAGE_URI = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="


class ZoomTextBrowser(QTextBrowser):
    """QTextBrowser with Ctrl+mouse-wheel zoom requests."""

    zoom_delta_requested = Signal(int)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoom_delta_requested.emit(1 if delta > 0 else -1)
                event.accept()
                return

        super().wheelEvent(event)


_SHARED_WEB_PROFILE = None


def _load_webengine_types() -> bool:
    """Load Qt WebEngine only when an HTML message first needs rendering."""
    global QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    global QWebEngineUrlRequestInterceptor, QWebEngineView
    global ZoomWebEngineView, MailWebEnginePage, RemoteContentInterceptor
    global _WEBENGINE_IMPORT_ATTEMPTED
    if _WEBENGINE_IMPORT_ATTEMPTED:
        return QWebEngineView is not None
    _WEBENGINE_IMPORT_ATTEMPTED = True
    try:
        from PySide6.QtWebEngineCore import (
            QWebEnginePage as WebEnginePage,
            QWebEngineProfile as WebEngineProfile,
            QWebEngineSettings as WebEngineSettings,
            QWebEngineUrlRequestInterceptor as WebEngineUrlRequestInterceptor,
        )
        from PySide6.QtWebEngineWidgets import QWebEngineView as WebEngineView
    except Exception:  # pragma: no cover - minimal PySide installs.
        return False

    QWebEnginePage = WebEnginePage
    QWebEngineProfile = WebEngineProfile
    QWebEngineSettings = WebEngineSettings
    QWebEngineUrlRequestInterceptor = WebEngineUrlRequestInterceptor
    QWebEngineView = WebEngineView

    class ZoomWebEngineView(WebEngineView):
        """QWebEngineView with Ctrl+mouse-wheel zoom requests."""

        zoom_delta_requested = Signal(int)

        def wheelEvent(self, event) -> None:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                if delta:
                    self.zoom_delta_requested.emit(1 if delta > 0 else -1)
                    event.accept()
                    return
            super().wheelEvent(event)

    class MailWebEnginePage(WebEnginePage):
        """Keeps message clicks out of the embedded HTML viewer."""

        def acceptNavigationRequest(self, url, navigation_type, is_main_frame: bool) -> bool:
            scheme = url.scheme().lower()
            if is_main_frame and scheme in {"http", "https", "mailto"}:
                if navigation_type == WebEnginePage.NavigationType.NavigationTypeLinkClicked:
                    QDesktopServices.openUrl(url)
                return False
            return super().acceptNavigationRequest(url, navigation_type, is_main_frame)

    class RemoteContentInterceptor(WebEngineUrlRequestInterceptor):
        """Blocks remote message resources until the user explicitly allows them."""

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.allow_remote_content = False
            self.allowed_inline_root: str | None = None
            self.allowed_inline_roots: set[str] = set()
            self.allowed_inline_files: set[str] = set()

        def set_allowed_inline_root(
            self,
            path: Path | None,
            allowed_files: set[Path] | None = None,
        ) -> None:
            self.allowed_inline_root = self._normalized_trusted_path(path) if path is not None else None
            self.allowed_inline_roots = set()
            self.allowed_inline_files = set()
            if path is None:
                return
            trusted_paths = {path, *(allowed_files or set())}
            self.allowed_inline_roots.add(self.allowed_inline_root)
            for trusted_path in trusted_paths:
                normalized = self._normalized_trusted_path(trusted_path)
                if trusted_path == path:
                    self.allowed_inline_roots.add(normalized)
                else:
                    self.allowed_inline_files.add(normalized)
                try:
                    # These are app-generated paths, never request URL paths.
                    resolved = trusted_path.resolve(strict=False)
                except OSError:
                    continue
                resolved_normalized = self._normalized_trusted_path(resolved)
                if trusted_path == path:
                    self.allowed_inline_roots.add(resolved_normalized)
                else:
                    self.allowed_inline_files.add(resolved_normalized)

        @staticmethod
        def _normalized_trusted_path(path: Path) -> str:
            return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))

        def interceptRequest(self, info) -> None:
            request_url = info.requestUrl()
            scheme = request_url.scheme().lower()
            if scheme in {"data", "about", "blob"}:
                return
            if scheme in {"http", "https"}:
                if not self.allow_remote_content:
                    info.block(True)
                return
            if scheme == "file" and not request_url.host() and self.allowed_inline_root is not None:
                resource_path = request_url.toLocalFile()
                if not self._is_unc_or_device_path(resource_path):
                    try:
                        if not self._is_unambiguous_absolute_path(resource_path):
                            info.block(True)
                            return
                        candidate_path = resource_path
                        if os.name == "nt":
                            candidate_path = candidate_path.replace("/", "\\")
                            if re.match(r"^\\[a-zA-Z]:[\\/]", candidate_path):
                                candidate_path = candidate_path[1:]
                        candidate = os.path.normcase(os.path.normpath(candidate_path))
                        if candidate in self.allowed_inline_files:
                            for root in self.allowed_inline_roots:
                                try:
                                    contained = os.path.commonpath((root, candidate)) == root
                                except ValueError:
                                    # Trusted TEMP aliases can be on different drives.
                                    continue
                                if contained:
                                    return
                    except (OSError, ValueError):
                        pass
            info.block(True)

        @staticmethod
        def _is_unc_or_device_path(path: str) -> bool:
            normalized = path.replace("/", "\\")
            return normalized.startswith(("\\\\", "\\?\\", "\\.\\"))

        @classmethod
        def _is_unambiguous_absolute_path(cls, path: str) -> bool:
            if os.name == "nt":
                path = path.replace("/", "\\")
                if re.match(r"^\\[a-zA-Z]:[\\/]", path):
                    path = path[1:]
                if not os.path.isabs(path):
                    return False
                _drive, tail = os.path.splitdrive(path)
                if ":" in tail:
                    return False
                for component in tail.split("\\"):
                    if component != component.rstrip(". "):
                        return False
                    base_name = component.split(".", 1)[0].upper()
                    if base_name in {
                        "CON", "PRN", "AUX", "NUL",
                        *(f"COM{index}" for index in range(1, 10)),
                        *(f"LPT{index}" for index in range(1, 10)),
                    }:
                        return False
                return True
            if not os.path.isabs(path):
                return False
            return all(component == component.rstrip(". ") for component in path.split("/"))

    return True


def _get_shared_web_profile() -> QWebEngineProfile | None:
    global _SHARED_WEB_PROFILE
    if _SHARED_WEB_PROFILE is None and QWebEngineProfile is not None:
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance()
        _SHARED_WEB_PROFILE = QWebEngineProfile(app) if app is not None else QWebEngineProfile()
    return _SHARED_WEB_PROFILE


class MessageBodyWidget(QWidget):
    """Displays the plain text and HTML bodies of an email."""

    open_in_browser_requested = Signal()
    print_busy_changed = Signal(bool)

    _resource_attr_pattern = re.compile(
        r"(?P<prefix>\b(?:src|background)\s*=\s*)(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
        re.IGNORECASE | re.DOTALL,
    )
    _srcset_attr_pattern = re.compile(
        r"(?P<prefix>\bsrcset\s*=\s*)(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
        re.IGNORECASE | re.DOTALL,
    )
    _css_url_pattern = re.compile(r"url\((?P<quote>[\"']?)(?P<value>.*?)(?P=quote)\)", re.IGNORECASE)
    _invalid_filename_chars = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
    _reserved_windows_names = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._inline_temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._inline_temp_files: set[Path] = set()
        self._current_email: ParsedEmail | None = None
        self._current_prepared_html = ""
        self._current_render_failed = False
        self._base_point_size = self.font().pointSizeF() or 10.0
        self._zoom_percent = 100
        self._remote_images_auto_load = False
        self._remote_images_allowed = False
        self._remote_content_interceptors: list[RemoteContentInterceptor] = []

        self._tabs = QTabWidget(self)
        self._plain_browser = ZoomTextBrowser(self)
        self._html_container = QWidget(self)
        self._html_view: QWidget | None = None
        self._html_browser: QWidget | None = None
        self._html_placeholder_label = QLabel(self._html_container)
        self._remote_notice_label = QLabel(self)
        self._load_remote_images_button = QPushButton(self)
        self._open_browser_button = QPushButton(self)
        self._zoom_out_button = QPushButton("-", self)
        self._zoom_in_button = QPushButton("+", self)
        self._zoom_reset_button = QPushButton("100%", self)
        self._zoom_label = QLabel("100%", self)
        self._plain_notice_label = QLabel(self)

        self._plain_browser.setOpenExternalLinks(False)
        self._plain_browser.zoom_delta_requested.connect(self._change_zoom_by_steps)
        self._zoom_out_button.clicked.connect(lambda: self._change_zoom_by_steps(-1))
        self._zoom_in_button.clicked.connect(lambda: self._change_zoom_by_steps(1))
        self._zoom_reset_button.clicked.connect(self.reset_zoom)
        self._load_remote_images_button.clicked.connect(self._allow_remote_images)
        self._open_browser_button.clicked.connect(lambda: self.open_in_browser_requested.emit())

        reset_shortcut = QShortcut(QKeySequence("Ctrl+0"), self)
        reset_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        reset_shortcut.activated.connect(self.reset_zoom)
        self._reset_zoom_shortcut = reset_shortcut

        for seq in (QKeySequence.StandardKey.ZoomIn, QKeySequence("Ctrl+=")):
            sc = QShortcut(seq, self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda: self._change_zoom_by_steps(1))
        sc_out = QShortcut(QKeySequence.StandardKey.ZoomOut, self)
        sc_out.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_out.activated.connect(lambda: self._change_zoom_by_steps(-1))

        for button in (self._zoom_out_button, self._zoom_in_button, self._zoom_reset_button):
            button.setFixedWidth(52)
        self._zoom_label.setMinimumWidth(46)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        remote_layout = QHBoxLayout()
        remote_layout.setContentsMargins(0, 0, 0, 0)
        remote_layout.addWidget(self._remote_notice_label)
        remote_layout.addWidget(self._load_remote_images_button)
        remote_layout.addStretch(1)

        html_layout = QVBoxLayout(self._html_container)
        html_layout.setContentsMargins(0, 0, 0, 0)
        html_layout.addWidget(self._html_placeholder_label)
        html_layout.addLayout(remote_layout)

        self._tabs.addTab(self._plain_browser, "")
        self._tabs.addTab(self._html_container, "")
        self._tabs.currentChanged.connect(self._on_current_tab_changed)
        self._plain_notice_label.setVisible(False)
        self._plain_notice_label.setObjectName("plainNotice")
        self._remote_notice_label.setObjectName("remoteNotice")

        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(self._open_browser_button)
        zoom_layout.addStretch(1)
        zoom_layout.addWidget(self._zoom_out_button)
        zoom_layout.addWidget(self._zoom_label)
        zoom_layout.addWidget(self._zoom_in_button)
        zoom_layout.addWidget(self._zoom_reset_button)

        self._search_bar = SearchBarWidget(self)
        self._search_bar.search_requested.connect(self._handle_search)
        self._search_bar.search_cleared.connect(self._handle_search_cleared)

        self._search_matches: list[QTextCursor] = []
        self._current_match_index: int = -1
        self._last_search_text: str = ""
        self._last_search_case: bool = False
        self._active_printer: object | None = None
        self._print_job_token: object | None = None
        self._deferred_render_pending = False
        self._deferred_clear_pending = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(zoom_layout)
        layout.addWidget(self._search_bar)
        layout.addWidget(self._plain_notice_label)
        layout.addWidget(self._tabs)

        self.retranslate_ui()
        self.clear()

    def clear(self) -> None:
        if self.print_busy:
            self._deferred_clear_pending = True
            self._deferred_render_pending = False
            return
        self._deferred_clear_pending = False
        self._deferred_render_pending = False
        self._current_email = None
        self._current_prepared_html = ""
        self._current_render_failed = False
        self._remote_images_allowed = self._remote_images_auto_load
        self._clear_inline_temp_dir()
        self._zoom_percent = 100
        self._apply_zoom_controls()
        self._plain_browser.setPlainText(tr("message.plain_placeholder"))
        self._set_html_placeholder(tr("message.html_placeholder"))
        self._tabs.setCurrentIndex(0)
        self._update_tab_dependent_controls()

    def retranslate_ui(self) -> None:
        self._remote_notice_label.setText(tr("message.remote_blocked"))
        self._load_remote_images_button.setText(tr("message.remote_show"))
        self._plain_notice_label.setText(tr("message.generated_plain_notice"))
        self._open_browser_button.setText(tr("button.open_browser"))
        self._search_bar.retranslate_ui()
        self._tabs.setTabText(0, tr("message.tab.plain"))
        self._tabs.setTabText(1, tr("message.tab.html"))
        if self._current_email is None:
            if self.print_busy:
                self._deferred_clear_pending = True
                self._deferred_render_pending = False
            else:
                self._plain_browser.setPlainText(tr("message.plain_placeholder"))
                self._set_html_placeholder(tr("message.html_placeholder"))
        else:
            self._render_email()

    def set_email(self, email: ParsedEmail) -> None:
        self._deferred_clear_pending = False
        self._handle_search_cleared()
        self._current_email = email
        self._remote_images_allowed = self._remote_images_auto_load
        self._render_email()
        if self.print_busy:
            self._update_tab_dependent_controls()
            return
        if self._search_bar.is_open() and self._search_bar.query():
            self._handle_search(
                self._search_bar.query(),
                True,
                self._search_bar.is_case_sensitive(),
            )

    def set_remote_images_auto_load(self, enabled: bool) -> None:
        self._remote_images_auto_load = bool(enabled)
        self._remote_images_allowed = self._remote_images_auto_load
        if self._current_email is not None:
            self._render_email()
        else:
            self._update_remote_controls()

    @property
    def zoom_percent(self) -> int:
        return self._zoom_percent

    @property
    def print_busy(self) -> bool:
        return self._print_job_token is not None

    def reset_zoom(self) -> None:
        self.set_zoom_percent(100)

    def set_zoom_percent(self, percent: int) -> None:
        percent = max(50, min(200, int(percent)))
        if percent == self._zoom_percent:
            self._apply_zoom_controls()
            return

        self._zoom_percent = percent
        self._apply_zoom_controls()

    def _change_zoom_by_steps(self, steps: int) -> None:
        self.set_zoom_percent(self._zoom_percent + (steps * 25))

    def _allow_remote_images(self) -> None:
        self._remote_images_allowed = True
        self._render_email()

    def _render_email(self) -> None:
        if self.print_busy:
            self._deferred_render_pending = True
            return
        if self._current_email is None:
            return

        self._current_render_failed = False
        email = self._current_email
        plain_text = email.plain_body.strip() or tr("message.no_plain")
        html_text = email.html_body.strip()

        self._plain_browser.setPlainText(plain_text)
        if html_text:
            prepared_html = self._prepare_html(email, allow_remote_resources=self._remote_images_allowed)
            self._current_prepared_html = prepared_html
            self._set_html_content(prepared_html)
            self._tabs.setCurrentIndex(1)
        else:
            self._current_prepared_html = ""
            self._clear_inline_temp_dir()
            self._set_html_placeholder(tr("message.html_empty"))
            self._tabs.setCurrentIndex(0)
        self._update_tab_dependent_controls()

    def _apply_zoom_controls(self) -> None:
        self._zoom_label.setText(f"{self._zoom_percent}%")
        self._zoom_out_button.setEnabled(self._zoom_percent > 50)
        self._zoom_in_button.setEnabled(self._zoom_percent < 200)

        point_size = self._base_point_size * self._zoom_percent / 100
        self._plain_browser.setStyleSheet(f"QTextBrowser {{ font-size: {point_size:.1f}pt; }}")
        if isinstance(self._html_view, ZoomTextBrowser):
            self._html_view.setStyleSheet(f"QTextBrowser {{ font-size: {point_size:.1f}pt; }}")
        elif QWebEngineView is not None and isinstance(self._html_view, QWebEngineView):
            self._html_view.setZoomFactor(self._zoom_percent / 100)

    def _zoomed_html(self, html_body: str) -> str:
        style = f"<style>body {{ font-size: {self._zoom_percent}%; }}</style>"
        if re.search(r"</head>", html_body, re.IGNORECASE):
            return re.sub(r"</head>", f"{style}</head>", html_body, count=1, flags=re.IGNORECASE)
        return f"{style}{html_body}"

    def _on_current_tab_changed(self, _index: int) -> None:
        self._handle_search_cleared()
        self._update_tab_dependent_controls()
        if self._search_bar.is_open() and self._search_bar.query():
            self._handle_search(
                self._search_bar.query(),
                True,
                self._search_bar.is_case_sensitive(),
            )

    def show_search_bar(self) -> None:
        self._search_bar.show_and_focus()

    def find_next(self) -> None:
        if self._search_bar.is_open():
            self._search_bar.find_next()
        else:
            self.show_search_bar()

    def find_previous(self) -> None:
        if self._search_bar.is_open():
            self._search_bar.find_previous()
        else:
            self.show_search_bar()

    def print_content(self, printer: object, on_finished: object | None = None) -> None:
        """현재 활성화된 탭의 본문을 인쇄합니다."""
        if self._active_printer is not None:
            if callable(on_finished):
                on_finished(False)
            return
        self._active_printer = printer
        job_token = object()
        self._print_job_token = job_token
        self._open_browser_button.setEnabled(False)
        self.print_busy_changed.emit(True)
        print_signal_connections: list[tuple[object, object]] = []

        def finish(ok: bool) -> None:
            if self._print_job_token is not job_token:
                return
            for signal, callback in print_signal_connections:
                try:
                    signal.disconnect(callback)
                except (RuntimeError, TypeError):
                    pass
            print_signal_connections.clear()
            self._print_job_token = None
            self._active_printer = None
            self.print_busy_changed.emit(False)
            try:
                if self._deferred_clear_pending:
                    self.clear()
                elif self._deferred_render_pending:
                    self._deferred_render_pending = False
                    self._render_email()
                    if self._search_bar.is_open() and self._search_bar.query():
                        self._handle_search(
                            self._search_bar.query(),
                            True,
                            self._search_bar.is_case_sensitive(),
                        )
            except Exception:
                _LOGGER.exception("Deferred message body render failed after printing")
                self._deferred_render_pending = False
                self._current_prepared_html = ""
                self._current_render_failed = True
                try:
                    if self._current_email is None:
                        self._plain_browser.setPlainText(tr("message.plain_placeholder"))
                        self._set_html_placeholder(tr("message.html_placeholder"))
                    else:
                        self._plain_browser.setPlainText(
                            self._current_email.plain_body.strip() or tr("message.no_plain")
                        )
                        message = (
                            tr("message.html_render_failed")
                            if self._current_email.html_body.strip()
                            else tr("message.html_empty")
                        )
                        self._set_html_placeholder(message)
                except Exception:
                    pass
            finally:
                try:
                    self._update_tab_dependent_controls()
                except Exception:
                    pass
                if callable(on_finished):
                    on_finished(ok)

        is_plain = (
            self._tabs.currentIndex() == 0
            or self._html_view is None
            or isinstance(self._html_view, ZoomTextBrowser)
        )
        if is_plain:
            try:
                browser = (
                    self._plain_browser
                    if self._tabs.currentIndex() == 0 or self._html_view is None
                    else self._html_view
                )
                browser.document().print_(printer)
                print_ok = True
            except Exception:
                print_ok = False
            finish(print_ok)
        else:
            if QWebEngineView is not None and isinstance(self._html_view, QWebEngineView):
                view = self._html_view
                print_func = getattr(view, "print_", None) or getattr(view, "print", None)
                if print_func is None or not hasattr(view, "printFinished"):
                    finish(False)
                    return
                try:
                    finished_signal = view.printFinished
                    finished_signal.connect(finish, Qt.ConnectionType.SingleShotConnection)
                    print_signal_connections.append((finished_signal, finish))
                    page = view.page() if hasattr(view, "page") else None
                    terminated_signal = getattr(page, "renderProcessTerminated", None)
                    if terminated_signal is not None:
                        def on_render_terminated(*_args) -> None:
                            finish(False)

                        terminated_signal.connect(on_render_terminated)
                        print_signal_connections.append((terminated_signal, on_render_terminated))
                    print_func(printer)
                except Exception:
                    finish(False)
            else:
                finish(False)

    def _handle_search(self, text: str, forward: bool, case_sensitive: bool) -> None:
        is_plain = (
            self._tabs.currentIndex() == 0
            or self._html_view is None
            or isinstance(self._html_view, ZoomTextBrowser)
        )
        if is_plain:
            target_browser = (
                self._plain_browser
                if self._tabs.currentIndex() == 0 or self._html_view is None
                else self._html_view
            )
            if text != self._last_search_text or case_sensitive != self._last_search_case:
                self._last_search_text = text
                self._last_search_case = case_sensitive
                self._search_matches = []
                doc = target_browser.document()
                find_flags = QTextDocument.FindFlag(0)
                if case_sensitive:
                    find_flags |= QTextDocument.FindFlag.FindCaseSensitively
                cursor = doc.find(text, 0, find_flags)
                while not cursor.isNull():
                    self._search_matches.append(cursor)
                    cursor = doc.find(text, cursor, find_flags)
                self._current_match_index = 0 if self._search_matches else -1
            else:
                if self._search_matches:
                    if forward:
                        self._current_match_index = (self._current_match_index + 1) % len(self._search_matches)
                    else:
                        self._current_match_index = (self._current_match_index - 1) % len(self._search_matches)

            if not self._search_matches:
                target_browser.setExtraSelections([])
                self._search_bar.set_match_status(0, 0)
                return

            cur = self._search_matches[self._current_match_index]
            target_browser.setTextCursor(cur)

            fmt_match = QTextCharFormat()
            fmt_match.setBackground(QColor(255, 255, 0, 140))
            fmt_current = QTextCharFormat()
            fmt_current.setBackground(QColor(255, 165, 0, 220))

            selections: list[QTextEdit.ExtraSelection] = []
            for idx, match_cursor in enumerate(self._search_matches):
                sel = QTextEdit.ExtraSelection()
                sel.cursor = match_cursor
                sel.format = fmt_current if idx == self._current_match_index else fmt_match
                selections.append(sel)
            target_browser.setExtraSelections(selections)
            self._search_bar.set_match_status(self._current_match_index + 1, len(self._search_matches))
        else:
            if QWebEngineView is not None and isinstance(self._html_view, QWebEngineView):
                flags = QWebEnginePage.FindFlag(0)
                if not forward:
                    flags |= QWebEnginePage.FindFlag.FindBackward
                if case_sensitive:
                    flags |= QWebEnginePage.FindFlag.FindCaseSensitively

                def on_found(res: object) -> None:
                    if hasattr(res, "numberOfMatches") and hasattr(res, "activeMatch"):
                        self._search_bar.set_match_status(res.activeMatch(), res.numberOfMatches())
                    elif isinstance(res, bool):
                        self._search_bar.set_match_status(1 if res else 0, 1 if res else 0)
                    else:
                        self._search_bar.set_match_status(1 if bool(res) else 0, 1 if bool(res) else 0)

                self._html_view.findText(text, flags, on_found)

    def _handle_search_cleared(self) -> None:
        self._plain_browser.setExtraSelections([])
        if isinstance(self._html_view, ZoomTextBrowser):
            self._html_view.setExtraSelections([])
        elif QWebEngineView is not None and isinstance(self._html_view, QWebEngineView):
            self._html_view.findText("")
        self._search_matches = []
        self._current_match_index = -1
        self._last_search_text = ""
        self._search_bar.set_match_status(0, 0)

    def _update_tab_dependent_controls(self) -> None:
        self._update_plain_notice_visibility()
        self._update_remote_controls()
        self._open_browser_button.setEnabled(self._current_email is not None and not self.print_busy)

    def _update_plain_notice_visibility(self) -> None:
        is_plain_tab = self._tabs.currentWidget() == self._plain_browser
        is_generated = bool(self._current_email and self._current_email.plain_body_generated)
        self._plain_notice_label.setVisible(is_plain_tab and is_generated)

    def _update_remote_controls(self) -> None:
        has_blocked_remote = bool(
            self._current_email
            and not self._remote_images_allowed
            and self._has_remote_resource_reference(self._current_email.html_body)
        )
        self._remote_notice_label.setVisible(has_blocked_remote)
        self._load_remote_images_button.setVisible(has_blocked_remote)

    def current_prepared_html(self) -> str:
        if self._deferred_render_pending or self._deferred_clear_pending:
            return ""
        if self._current_email is None:
            return ""
        if self._current_render_failed:
            return self._plain_text_html(self._current_email.plain_body)
        if self._current_prepared_html.strip():
            return self._current_prepared_html
        if self._current_email.html_body.strip():
            return self._current_email.html_body
        return self._plain_text_html(self._current_email.plain_body)

    def _create_html_view(self) -> QWidget:
        if not _load_webengine_types():
            fallback = ZoomTextBrowser(self)
            fallback.setPlainText(tr("message.webengine_unavailable"))
            return fallback

        view = ZoomWebEngineView(self)
        profile = _get_shared_web_profile() or QWebEngineProfile(view)
        page = MailWebEnginePage(profile, view)
        interceptor = RemoteContentInterceptor(view)
        self._remote_content_interceptors.append(interceptor)
        page.setUrlRequestInterceptor(interceptor)
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        view.setPage(page)
        return view

    def _ensure_html_view(self) -> QWidget:
        """Create the HTML renderer on first use and reuse it for later messages."""
        if self._html_view is None:
            view = self._create_html_view()
            self._html_view = view
            self._html_browser = view
            if isinstance(view, ZoomTextBrowser):
                view.setOpenExternalLinks(False)
                view.zoom_delta_requested.connect(self._change_zoom_by_steps)
            elif QWebEngineView is not None and isinstance(view, QWebEngineView):
                view.zoom_delta_requested.connect(self._change_zoom_by_steps)
            layout = self._html_container.layout()
            layout.addWidget(view)
            self._html_placeholder_label.hide()
            self._apply_zoom_controls()
        return self._html_view

    def _set_html_content(self, html_body: str) -> None:
        self._set_web_content(self._ensure_html_view(), html_body, self._html_base_url())

    def _set_web_content(self, view: QWidget, html_body: str, base_url: QUrl) -> None:
        if isinstance(view, ZoomTextBrowser):
            view.setHtml(self._zoomed_html(html_body))
            return

        if QWebEngineView is None or not isinstance(view, QWebEngineView):
            return

        for interceptor in self._remote_content_interceptors:
            interceptor.allow_remote_content = self._remote_images_allowed
            interceptor.set_allowed_inline_root(
                Path(self._inline_temp_dir.name) if self._inline_temp_dir is not None else None,
                self._inline_temp_files,
            )

        page = view.page()
        page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            self._remote_images_allowed,
        )
        view.setZoomFactor(self._zoom_percent / 100)
        view.setHtml(html_body, base_url)

    def _set_html_placeholder(self, message: str) -> None:
        if self._html_view is None:
            self._html_placeholder_label.setText(message)
            self._html_placeholder_label.show()
            return
        if isinstance(self._html_view, ZoomTextBrowser):
            self._html_view.setPlainText(message)
            return
        if QWebEngineView is not None and isinstance(self._html_view, QWebEngineView):
            self._html_view.setZoomFactor(self._zoom_percent / 100)
            self._html_view.setHtml(f"<html><body><p>{html.escape(message)}</p></body></html>")

    def _plain_text_html(self, text: str) -> str:
        escaped = html.escape(text)
        return (
            "<html><body>"
            '<pre style="white-space: pre-wrap; font-family: inherit;">'
            f"{escaped}</pre></body></html>"
        )

    def _html_base_url(self) -> QUrl:
        if self._inline_temp_dir is not None:
            return QUrl.fromLocalFile(str(Path(self._inline_temp_dir.name)) + "/")
        return QUrl("about:blank")

    def _prepare_html(self, email: ParsedEmail, allow_remote_resources: bool = False) -> str:
        self._clear_inline_temp_dir()
        resource_to_uri: dict[str, str] = {}
        unresolved_refs: set[str] = set()

        if email.inline_resources:
            self._inline_temp_dir = tempfile.TemporaryDirectory(prefix="eml-viewer-inline-")
            temp_root = Path(self._inline_temp_dir.name)

            for index, resource in enumerate(email.inline_resources, start=1):
                extension = mimetypes.guess_extension(resource.content_type) or ""
                filename = self._safe_filename(resource.filename or f"inline-{index}{extension}")
                if not Path(filename).suffix and extension:
                    filename = f"{filename}{extension}"
                filename = f"{index}-{filename}"
                target_path = temp_root / filename
                try:
                    target_path.write_bytes(resource.payload)
                except OSError:
                    unresolved_refs.update(self._resource_keys(resource.content_id))
                    unresolved_refs.update(self._resource_keys(resource.content_location))
                    unresolved_refs.update(self._resource_keys(resource.filename))
                    continue
                self._inline_temp_files.add(target_path)
                for key in self._resource_keys(resource.content_id):
                    resource_to_uri[key] = target_path.as_uri()
                for key in self._resource_keys(resource.content_location):
                    resource_to_uri[key] = target_path.as_uri()
                for key in self._resource_keys(resource.filename):
                    resource_to_uri[key] = target_path.as_uri()

        def resolve_reference(value: str) -> str | None:
            for key in self._resource_keys(value):
                uri = resource_to_uri.get(key)
                if uri:
                    return uri
            if self._looks_like_embedded_reference(value):
                unresolved_refs.add(value)
            return None

        def safe_resource_value(value: str) -> str | None:
            if self._is_remote_url(value):
                if not allow_remote_resources:
                    return _TRANSPARENT_IMAGE_URI
                return f"https:{value}" if value.strip().startswith("//") else value
            resolved = resolve_reference(value)
            if resolved is not None:
                return resolved
            if self._is_unsafe_resource_reference(value):
                return _TRANSPARENT_IMAGE_URI
            return None

        def replace_attr(match: re.Match[str]) -> str:
            value = match.group("value")
            uri = safe_resource_value(value)
            if uri is None:
                return match.group(0)
            return f"{match.group('prefix')}{match.group('quote')}{uri}{match.group('quote')}"

        def replace_srcset(match: re.Match[str]) -> str:
            value = match.group("value")
            rewritten_items: list[str] = []
            for source, descriptor in self._srcset_items(value):
                uri = safe_resource_value(source) or source
                rewritten_items.append(f"{uri} {descriptor}".strip())
            rewritten = ", ".join(rewritten_items)
            return f"{match.group('prefix')}{match.group('quote')}{rewritten}{match.group('quote')}"

        def replace_css_url(match: re.Match[str]) -> str:
            value = match.group("value")
            uri = safe_resource_value(value)
            if uri is None:
                return match.group(0)
            quote = match.group("quote") or ""
            return f"url({quote}{uri}{quote})"

        prepared_html = self._resource_attr_pattern.sub(replace_attr, email.html_body)
        prepared_html = self._srcset_attr_pattern.sub(replace_srcset, prepared_html)
        prepared_html = self._css_url_pattern.sub(replace_css_url, prepared_html)
        if unresolved_refs:
            prepared_html += self._unresolved_resource_notice(len(unresolved_refs))
        return prepared_html

    def _safe_filename(self, filename: str) -> str:
        cleaned = self._invalid_filename_chars.sub("_", filename).strip(" .")
        if cleaned and Path(cleaned).stem.upper() in self._reserved_windows_names:
            cleaned_path = Path(cleaned)
            cleaned = f"{cleaned_path.stem}_{cleaned_path.suffix}" if cleaned_path.suffix else f"{cleaned}_"
        cleaned_path = Path(cleaned or "inline-resource")
        stem = cleaned_path.stem[:80]
        suffix = cleaned_path.suffix[:32]
        cleaned = f"{stem}{suffix}".strip(" .")
        return cleaned or "inline-resource"

    def _resource_keys(self, value: str) -> set[str]:
        if not value:
            return set()

        cleaned = html.unescape(unquote(str(value))).strip().strip("\"'<>")
        if not cleaned:
            return set()

        lowered = cleaned.lower()
        if lowered.startswith(("http://", "https://", "data:", "mailto:", "#")):
            return set()
        if lowered.startswith("cid:"):
            cleaned = cleaned[4:]
            lowered = cleaned.lower()

        parsed_path = urlparse(cleaned).path or cleaned
        candidates = {
            cleaned,
            lowered,
            cleaned.lstrip("./\\"),
            parsed_path,
            parsed_path.lstrip("./\\"),
            Path(parsed_path.replace("\\", "/")).name,
        }
        return {candidate.strip().strip("<>").lower() for candidate in candidates if candidate.strip()}

    def _srcset_items(self, value: str) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        for candidate in str(value).split(","):
            candidate = candidate.strip()
            if not candidate:
                continue
            parts = candidate.split(None, 1)
            source = parts[0]
            descriptor = parts[1] if len(parts) > 1 else ""
            items.append((source, descriptor))
        return items

    def _has_remote_resource_reference(self, html_body: str) -> bool:
        for match in self._resource_attr_pattern.finditer(html_body):
            if self._is_remote_url(match.group("value")):
                return True
        for match in self._srcset_attr_pattern.finditer(html_body):
            if any(self._is_remote_url(source) for source, _descriptor in self._srcset_items(match.group("value"))):
                return True
        for match in self._css_url_pattern.finditer(html_body):
            if self._is_remote_url(match.group("value")):
                return True
        return False

    def _is_remote_url(self, value: str) -> bool:
        value = html.unescape(str(value)).strip().lower()
        return value.startswith(("http://", "https://", "//"))

    def _is_unsafe_resource_reference(self, value: str) -> bool:
        cleaned = html.unescape(str(value)).strip()
        if not cleaned:
            return False
        lowered = cleaned.lower()
        if lowered.startswith(("data:", "about:", "blob:")):
            return False
        if urlparse(cleaned).scheme:
            return True
        if cleaned.startswith(("\\\\", "/")) or re.match(r"^[a-zA-Z]:[\\/]", cleaned):
            return True
        return any(part == ".." for part in cleaned.replace("\\", "/").split("/"))

    def _looks_like_embedded_reference(self, value: str) -> bool:
        keys = self._resource_keys(value)
        if not keys:
            return False
        lowered = value.lower().strip()
        return lowered.startswith("cid:") or any(
            key.endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg")) for key in keys
        )

    def _unresolved_resource_notice(self, count: int) -> str:
        return (
            '<hr><p style="color:#a15c00; font-size:90%;">'
            f"{tr('message.unresolved_images', count=count)}"
            "</p>"
        )

    def _clear_inline_temp_dir(self) -> None:
        if self._inline_temp_dir is not None:
            self._inline_temp_dir.cleanup()
            self._inline_temp_dir = None
        self._inline_temp_files.clear()
