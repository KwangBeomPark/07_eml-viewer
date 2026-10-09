from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication

from eml_viewer.gui.settings_dialog import SettingsDialog
from eml_viewer.models.app_settings import AppSettings

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_settings_dialog_checkboxes():
    app = QApplication.instance() or QApplication([])
    initial_settings = AppSettings(
        startup_with_windows=True,
        minimize_to_tray_on_close=False,
    )
    dialog = SettingsDialog(initial_settings)

    assert dialog.startup_with_windows is True
    assert dialog.minimize_to_tray_on_close is False

    # 체크박스 토글
    dialog._startup_with_windows_check.setChecked(False)
    dialog._minimize_to_tray_check.setChecked(True)

    assert dialog.startup_with_windows is False
    assert dialog.minimize_to_tray_on_close is True
