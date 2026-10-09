"""Canonical and legacy packaging entry points resolve the same project inputs."""

from pathlib import Path
import runpy
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from eml_viewer.gui.settings_dialog import SettingsDialog
from eml_viewer.models.app_settings import AppSettings


def test_canonical_and_legacy_spec_resolve_identical_inputs():
    root = Path(__file__).parents[1]
    definitions = []
    for relative in (
        "installer/eml_viewer.spec",
        "packaging/pyinstaller/eml_viewer.spec",
    ):
        path = root / relative
        captured = {}

        def analysis(scripts, captured=captured, **kwargs):
            captured.update(scripts=scripts, **kwargs)
            return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

        def empty(*args, **kwargs):
            return SimpleNamespace()
        runpy.run_path(
            str(path),
            init_globals={
                "SPECPATH": str(path.parent),
                "Analysis": analysis,
                "PYZ": empty,
                "EXE": empty,
                "COLLECT": empty,
            },
        )
        definitions.append(captured)
    assert definitions[0] == definitions[1]
    assert definitions[0]["scripts"] == [str(root / "src/eml_viewer/__main__.py")]
    assert Path(definitions[0]["datas"][0][0]) == root / "assets/app.ico"


def test_settings_dialog_shows_the_actual_service_directory(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(
        AppSettings(), settings_directory=tmp_path / "custom settings"
    )
    assert dialog._settings_location_label.text() == str(tmp_path / "custom settings")
    dialog.close()
    assert app is not None
