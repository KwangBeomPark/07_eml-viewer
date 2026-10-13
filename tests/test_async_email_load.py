from __future__ import annotations

import threading
import time
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eml_viewer.gui.main_window import MainWindow
from eml_viewer.models.email_data import ParsedEmail
from eml_viewer.services.attachment_service import AttachmentService
from eml_viewer.services.file_operation_service import FileOperationService
from eml_viewer.services.settings_service import SettingsService


class BlockingParser:
    def __init__(self) -> None:
        self.started: list[Path] = []
        self.release = threading.Event()
        self.first_started = threading.Event()
        self.blocked_name = "first.eml"

    def parse_file(self, path: str | Path) -> ParsedEmail:
        path = Path(path)
        self.started.append(path)
        self.first_started.set()
        if path.name == self.blocked_name:
            self.release.wait(5)
        if path.name == "bad.eml":
            raise ValueError("stale parse failure")
        return ParsedEmail(
            subject=path.stem,
            sender="",
            recipients="",
            date="",
            plain_body="",
            html_body="",
            source_path=None if path.name == "no-source.eml" else path,
        )


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path, app):
    parser = BlockingParser()
    file_ops = FileOperationService()
    window = MainWindow(
        parser=parser,
        attachment_service=AttachmentService(parser, file_ops),
        settings_service=SettingsService(tmp_path / "settings.json"),
        file_operation_service=file_ops,
        auto_check_update=False,
    )
    yield window, parser
    parser.release.set()
    window.close()
    _pump(app, lambda: window._email_load_thread is None, timeout=2)


def _pump(app: QApplication, predicate, timeout: float = 3) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return predicate()


def test_async_load_keeps_ui_responsive_and_latest_request_wins(window, app):
    win, parser = window
    heartbeat = threading.Event()
    win.load_email_async("first.eml")
    assert parser.first_started.wait(1)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(heartbeat.set)
    timer.start(0)
    win.load_email_async("bad.eml")
    win.load_email_async("latest.eml")
    app.processEvents()
    assert heartbeat.is_set()

    parser.release.set()
    assert _pump(app, lambda: win._current_email is not None and win._current_email.subject == "latest")
    assert parser.started == [Path("first.eml"), Path("latest.eml")]


def test_close_during_parse_discards_result_and_never_starts_pending(window, app):
    win, parser = window
    win.load_email_async("first.eml")
    assert parser.first_started.wait(1)
    win.load_email_async("pending.eml")
    win.close()
    parser.release.set()
    _pump(app, lambda: not win._email_load_thread or not win._email_load_thread.isRunning())
    app.processEvents()
    assert parser.started == [Path("first.eml")]
    assert win._current_email is None


def test_standalone_shutdown_helper_drains_only_orphaned_parser_workers(window, app):
    from eml_viewer.gui import main_window as main_window_module

    win, parser = window
    win.load_email_async("first.eml")
    assert parser.first_started.wait(1)
    thread = win._email_load_thread
    assert thread is not None

    win.close()
    assert thread in main_window_module._orphaned_email_threads
    assert app.property("emlViewerOrphanThreadCleanupConnected") is True

    parser.release.set()
    main_window_module._wait_for_orphaned_email_threads()
    app.processEvents()

    assert thread.isFinished()
    assert thread not in main_window_module._orphaned_email_threads


def test_current_parse_error_is_reported_after_stale_success_is_discarded(window, app):
    win, parser = window
    with patch.object(win, "_show_error") as show_error:
        win.load_email_async("first.eml")
        assert parser.first_started.wait(1)
        win.load_email_async("bad.eml")
        parser.release.set()
        assert _pump(app, lambda: show_error.called)
        assert show_error.call_args.args[1].args == ("stale parse failure",)
        assert win._current_email is None


def test_synchronous_load_supersedes_inflight_async_result(window, app):
    win, parser = window
    win.load_email_async("first.eml")
    assert parser.first_started.wait(1)
    win.load_email("direct.eml")
    parser.release.set()
    assert _pump(app, lambda: win._email_load_thread is None)
    assert win._current_email.subject == "direct"


def test_request_after_worker_stops_but_before_finished_event_replaces_pending(window, app):
    win, parser = window
    win.load_email_async("first.eml")
    assert parser.first_started.wait(1)
    win.load_email_async("pending-A.eml")

    running_slot = win._email_load_thread
    assert running_slot is not None
    parser.release.set()
    assert running_slot.wait(2)
    assert not running_slot.isRunning()

    # Do not pump Qt events: the finished signal is still queued to the UI thread.
    win.load_email_async("latest-B.eml")
    assert win._email_load_thread is running_slot
    assert _pump(
        app,
        lambda: win._current_email is not None
        and win._current_email.subject == "latest-B"
        and win._email_load_thread is None,
    )

    assert parser.started == [Path("first.eml"), Path("latest-B.eml")]


def test_repeated_previous_clicks_advance_from_pending_navigation_target(window, app, tmp_path):
    win, parser = window
    parser.blocked_name = "3.eml"
    paths = []
    for index in range(5):
        path = tmp_path / f"{index}.eml"
        path.write_text("placeholder", encoding="utf-8")
        paths.append(path)
    win._folder_emails = paths
    win._current_folder_index = 4

    win._navigate_prev_email()
    assert parser.first_started.wait(1)
    win._navigate_prev_email()
    win._navigate_prev_email()
    assert win._pending_navigation_index == 1

    parser.release.set()
    assert _pump(app, lambda: win._current_email is not None and win._current_email.subject == "1")
    assert parser.started == [paths[3], paths[1]]
    assert win._current_folder_index == 1


def test_removed_pending_navigation_target_is_cancelled_after_folder_shrinks(window, app, tmp_path):
    win, parser = window
    parser.blocked_name = "3.eml"
    paths = []
    for index in range(5):
        path = tmp_path / f"{index}.eml"
        path.write_text("placeholder", encoding="utf-8")
        paths.append(path)
    win._folder_emails = paths
    win._current_folder_index = 4

    win._navigate_prev_email()
    assert parser.first_started.wait(1)
    win._navigate_prev_email()
    assert win._pending_navigation_path == paths[2]

    paths[2].unlink()
    win._folder_navigation.invalidate(tmp_path)
    win._update_folder_navigation(paths[4])
    assert win._pending_navigation_path is None
    assert win._pending_email_load is None
    assert not win._pending_navigation_active
    win._navigate_prev_email()
    assert win._pending_email_load is not None
    assert Path(win._pending_email_load[1]) == paths[3]

    parser.release.set()
    assert _pump(app, lambda: win._current_email is not None and win._current_email_path == paths[3])
    assert parser.started == [paths[3], paths[3]]
    assert win._current_folder_index == 2


def test_existing_pending_navigation_target_is_remapped_after_folder_shrinks(window, app, tmp_path):
    win, parser = window
    parser.blocked_name = "4.eml"
    paths = []
    for index in range(6):
        path = tmp_path / f"{index}.eml"
        path.write_text("placeholder", encoding="utf-8")
        paths.append(path)
    win._folder_emails = paths
    win._current_folder_index = 5

    win._navigate_prev_email()
    assert parser.first_started.wait(1)
    win._navigate_prev_email()
    assert win._pending_navigation_path == paths[3]

    paths[0].unlink()
    win._folder_navigation.invalidate(tmp_path)
    win._update_folder_navigation(paths[5])
    assert win._pending_navigation_index == 2
    win._navigate_prev_email()
    assert Path(win._pending_email_load[1]) == paths[2]

    parser.release.set()
    assert _pump(app, lambda: win._current_email is not None and win._current_email_path == paths[2])
    assert parser.started == [paths[4], paths[2]]
    assert win._current_folder_index == 1


def test_missing_parsed_source_path_uses_requested_path_for_recent_and_folder(window, app, tmp_path):
    win, parser = window
    requested_path = tmp_path / "no-source.eml"
    requested_path.write_text("placeholder", encoding="utf-8")
    win.load_email_async(requested_path)

    assert _pump(app, lambda: win._current_email is not None)
    assert win._current_email.source_path is None
    assert str(requested_path) in win._settings_service.load_settings().recent_files
    assert win._current_email_path == requested_path
    assert win._folder_emails == [requested_path]


def test_folder_change_burst_invalidates_immediately_and_rescans_once(window, app):
    win, _parser = window
    win._current_email_path = Path("current.eml")
    with patch.object(win._folder_navigation, "invalidate") as invalidate, patch.object(
        win, "_update_folder_navigation"
    ) as update:
        for _ in range(4):
            win._on_folder_changed(str(Path("watched").resolve()))
        assert invalidate.call_count == 4
        assert _pump(app, lambda: update.called, timeout=1.5)
        assert update.call_count == 1


def test_close_stops_folder_watch_and_debounce_timer(window):
    win, _parser = window
    win._on_folder_changed(str(Path("watched").resolve()))
    win.close()
    assert not win._folder_change_timer.isActive()
    assert win._folder_watcher.directories() == []


def test_repeated_close_runs_window_cleanup_once(window):
    win, _parser = window
    manager = MagicMock()
    win._window_manager = manager
    with patch.object(win._settings_service, "save_window_geometry") as save_geometry:
        win.close()
        win.close()
        manager.unregister_window.assert_called_once_with(win)
        save_geometry.assert_called_once()


def test_standalone_window_is_retained_until_active_print_finishes(window):
    from eml_viewer.gui import main_window as main_window_module

    win, _parser = window
    win._body_widget._active_printer = object()
    win._body_widget._print_job_token = object()
    win.close()

    assert win in main_window_module._orphaned_print_windows
    assert not win.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    with patch.object(win, "deleteLater") as delete_later:
        win._body_widget._active_printer = None
        win._body_widget._print_job_token = None
        win._body_widget.print_busy_changed.emit(False)
        assert win not in main_window_module._orphaned_print_windows
        delete_later.assert_called_once()


def test_open_in_browser_action_is_blocked_while_print_is_busy(window):
    win, _parser = window
    win._display_email(
        ParsedEmail(
            subject="printing",
            sender="",
            recipients="",
            date="",
            plain_body="body",
            html_body="<html><body>content</body></html>",
        )
    )
    win._body_widget._active_printer = object()
    win._body_widget._print_job_token = object()
    win._body_widget.print_busy_changed.emit(True)
    with patch("eml_viewer.gui.main_window.QDesktopServices.openUrl") as open_url:
        assert not win._open_browser_action.isEnabled()
        win._open_browser_action.trigger()
        win._open_in_browser()
        open_url.assert_not_called()
    win._body_widget._active_printer = None
    win._body_widget._print_job_token = None
    win._body_widget.print_busy_changed.emit(False)


def _begin_pdf_export(win: MainWindow, target_path: Path, stack: ExitStack):
    win._display_email(
        ParsedEmail(
            subject="PDF check",
            sender="",
            recipients="",
            date="",
            plain_body="body",
            html_body="",
            source_path=Path("source.eml"),
        )
    )
    completion = {}
    info = stack.enter_context(patch("eml_viewer.gui.dialogs.show_info"))
    error = stack.enter_context(patch.object(win, "_show_error"))
    stack.enter_context(
        patch(
            "eml_viewer.gui.main_window.QFileDialog.getSaveFileName",
            return_value=(str(target_path), "PDF (*.pdf)"),
        )
    )
    stack.enter_context(patch("eml_viewer.gui.main_window.QPrinter"))

    def capture_print(_printer, on_finished=None):
        completion["callback"] = on_finished

    stack.enter_context(patch.object(win._body_widget, "print_content", side_effect=capture_print))
    win._export_as_pdf()
    return completion, info, error


def test_pdf_export_does_not_report_success_without_output(window, tmp_path):
    win, _parser = window
    target = tmp_path / "missing.pdf"
    with ExitStack() as stack:
        completion, info, error = _begin_pdf_export(win, target, stack)
        completion["callback"](True)
        info.assert_not_called()
        error.assert_called_once()


def test_pdf_export_does_not_report_success_for_unchanged_existing_output(window, tmp_path):
    win, _parser = window
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"old pdf")
    with ExitStack() as stack:
        completion, info, error = _begin_pdf_export(win, target, stack)
        completion["callback"](True)
        info.assert_not_called()
        error.assert_called_once()


def test_pdf_export_reports_new_nonempty_output(window, tmp_path):
    win, _parser = window
    target = tmp_path / "new.pdf"
    with ExitStack() as stack:
        completion, info, error = _begin_pdf_export(win, target, stack)
        target.write_bytes(b"new pdf output")
        completion["callback"](True)
        info.assert_called_once()
        error.assert_not_called()


def test_pdf_export_reports_error_when_existing_output_is_unreadable(window, tmp_path):
    win, _parser = window
    target = tmp_path / "locked.pdf"
    target.write_bytes(b"old pdf")
    with ExitStack() as stack:
        completion, info, error = _begin_pdf_export(win, target, stack)
        original_stat = Path.stat

        def locked_stat(path, *args, **kwargs):
            if path == target:
                raise PermissionError("locked output")
            return original_stat(path, *args, **kwargs)

        with patch.object(Path, "stat", locked_stat):
            completion["callback"](True)
        info.assert_not_called()
        error.assert_called_once()
