"""Watch real synthetic filesystem changes and keep navigation current."""
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PySide6.QtWidgets import QApplication
from eml_viewer.gui.main_window import MainWindow
from eml_viewer.services.attachment_service import AttachmentService
from eml_viewer.services.eml_parser import EmlParser
from eml_viewer.services.file_operation_service import FileOperationService
from eml_viewer.services.settings_service import SettingsService


def pump(app, predicate):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def make_window(tmp_path):
    app = QApplication.instance() or QApplication([])
    parser = EmlParser()
    operations = FileOperationService()
    window = MainWindow(parser, AttachmentService(parser, operations),
                        SettingsService(tmp_path / "settings.json"), operations,
                        auto_check_update=False)
    return app, window


def test_watcher_reflects_add_rename_delete_and_reuses_listing(tmp_path):
    folder = tmp_path / "mail"
    folder.mkdir()
    current = folder / "a.eml"
    current.write_text("Subject: a\n\nPlain", encoding="utf-8")
    app, window = make_window(tmp_path)
    try:
        window.load_email(current)
        assert window._folder_watcher.directories()
        with patch("eml_viewer.services.folder_navigation.os.scandir",
                   wraps=os.scandir) as scan:
            window._update_folder_navigation(current)
            window._update_folder_navigation(current)
            assert scan.call_count == 0
        second = folder / "b.eml"
        second.write_text("Subject: b\n\nPlain", encoding="utf-8")
        assert pump(app, lambda: second in window._folder_emails)
        renamed = folder / "c.msg"
        second.rename(renamed)
        assert pump(app, lambda: renamed in window._folder_emails and second not in window._folder_emails)
        renamed.unlink()
        assert pump(app, lambda: window._folder_emails == [current])
    finally:
        window.close()
        app.processEvents()


def test_unavailable_watcher_falls_back_to_new_scan(tmp_path):
    current = tmp_path / "a.eml"
    current.write_text("Subject: a\n\nPlain", encoding="utf-8")
    app, window = make_window(tmp_path)
    try:
        with patch.object(window._folder_watcher, "addPath", return_value=False):
            window.load_email(current)
            second = tmp_path / "b.eml"
            second.write_text("Subject: b\n\nPlain", encoding="utf-8")
            window._update_folder_navigation(current)
            assert second in window._folder_emails
    finally:
        window.close()
        app.processEvents()
