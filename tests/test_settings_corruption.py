"""Fallback defaults and automatic updates cannot erase damaged settings."""

import pytest

from eml_viewer.models.app_settings import AppSettings
from eml_viewer.services.settings_service import SettingsService
from eml_viewer.services import settings_service


@pytest.mark.parametrize("original", [b'{"partial":', b'[]', b'\xff'])
@pytest.mark.parametrize("operation", ["settings", "geometry", "recipients", "recent_file"])
def test_damaged_settings_remain_byte_identical(tmp_path, original, operation):
    path = tmp_path / "settings.json"
    path.write_bytes(original)
    service = SettingsService(path, auto_migrate=False)
    assert isinstance(service.load_settings(), AppSettings)
    actions = {
        "settings": lambda: service.save_settings(service.load_settings()),
        "geometry": lambda: service.save_window_geometry(1, 2, 640, 480),
        "recipients": lambda: service.save_recent_recipients(["sample@example.test"]),
        "recent_file": lambda: service.add_recent_file(tmp_path / "sample.eml"),
    }
    with pytest.raises(OSError, match="damaged"):
        actions[operation]()
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_damage_detected_after_temp_write_is_not_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_bytes(b'{}')
    damaged = b'{"external interrupted update":'
    monkeypatch.setattr(settings_service.os, "fsync", lambda _: path.write_bytes(damaged))
    with pytest.raises(OSError):
        SettingsService(path, auto_migrate=False).save_settings(AppSettings())
    assert path.read_bytes() == damaged
    assert list(tmp_path.iterdir()) == [path]
