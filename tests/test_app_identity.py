from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eml_viewer import app_identity
from eml_viewer.services.settings_service import SettingsService


class AppIdentityTest(unittest.TestCase):
    def test_constants_and_ids(self) -> None:
        self.assertEqual(app_identity.PRODUCT_ID, "App07_EmlViewer")
        self.assertEqual(app_identity.DISPLAY_NAME, "EML Viewer")
        self.assertEqual(app_identity.INSTALL_DIR, "EML Viewer")
        self.assertEqual(app_identity.USER_SETTING_DIR, "UserSetting")
        self.assertEqual(app_identity.CONFIG_FILENAME, "settings.json")
        self.assertEqual(app_identity.INSTALLER_APP_ID, "{A9D9B7C3-04B8-4D2F-B28C-5B18C01C9CE1}")
        self.assertEqual(app_identity.WINDOWS_APP_ID, "emlviewer.desktop.v1")

    def test_user_data_dir_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_exe = Path(temp_dir) / "App07_EmlViewer.exe"
            fake_exe.touch()
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(fake_exe)):
                data_dir = app_identity.user_data_dir()
                self.assertEqual(data_dir, Path(temp_dir) / "UserSetting")

    def test_version_from_tag(self) -> None:
        self.assertEqual(app_identity.version_from_tag("v0.1.15"), "0.1.15")
        self.assertEqual(app_identity.version_from_tag("0.1.15"), "0.1.15")
        self.assertIsNone(app_identity.version_from_tag("v0.1.15-beta"))

    def test_legacy_settings_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_file = Path(temp_dir) / "legacy" / "settings.json"
            legacy_file.parent.mkdir(parents=True, exist_ok=True)
            legacy_file.write_text('{"language": "en", "theme": "dark", "window_width": 1280}', encoding="utf-8")

            new_target = Path(temp_dir) / "new_app" / "UserSetting" / "settings.json"

            with patch("eml_viewer.services.settings_service.legacy_roaming_settings_path", return_value=legacy_file):
                service = SettingsService(settings_path=new_target, auto_migrate=True)
                self.assertTrue(new_target.exists())
                loaded = service.load_settings()
                self.assertEqual(loaded.language, "en")
                self.assertEqual(loaded.theme, "dark")
                self.assertEqual(loaded.window_width, 1280)

    def test_suite_registry_fallback_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            service = SettingsService(settings_path=settings_path)

            with patch("eml_viewer.services.settings_service.get_suite_common_fallback") as mock_fallback:
                def fake_fallback(key: str, default: str = "") -> str:
                    if key == "SMTPServer":
                        return "smtp.example.com"
                    if key == "SMTPPort":
                        return "587"
                    return default

                mock_fallback.side_effect = fake_fallback

                loaded = service.load_settings()
                self.assertEqual(loaded.smtp_host, "smtp.example.com")
                self.assertEqual(loaded.smtp_port, 587)


if __name__ == "__main__":
    unittest.main()
