from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eml_viewer.models.app_settings import AppSettings
from eml_viewer.services.settings_service import SettingsService


class SettingsServiceTest(unittest.TestCase):
    def test_explicit_default_smtp_values_override_suite_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            service = SettingsService(path)
            service.save_settings(AppSettings(smtp_host="", smtp_port=25))
            with patch("eml_viewer.services.settings_service.get_suite_common_fallback") as fallback:
                loaded = service.load_settings()
            self.assertEqual(loaded.smtp_host, "")
            self.assertEqual(loaded.smtp_port, 25)
            fallback.assert_not_called()

    def test_missing_smtp_keys_inherit_suite_defaults_individually(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            for data, expected_host, expected_port in (
                ({"smtp_host": "user.example.com"}, "user.example.com", 587),
                ({"smtp_port": 25}, "smtp.example.com", 25),
                ({"language": "en"}, "smtp.example.com", 587),
            ):
                with self.subTest(data=data):
                    path.write_text(json.dumps(data), encoding="utf-8")
                    with patch(
                        "eml_viewer.services.settings_service.get_suite_common_fallback",
                        side_effect=lambda key, default: {
                            "SMTPServer": "smtp.example.com", "SMTPPort": "587",
                        }.get(key, default),
                    ):
                        loaded = SettingsService(path).load_settings()
                    self.assertEqual(loaded.smtp_host, expected_host)
                    self.assertEqual(loaded.smtp_port, expected_port)

    def test_invalid_suite_ports_do_not_replace_app_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SettingsService(Path(temp_dir) / "settings.json")
            for port in ("0", "65536", "-1", "bad", "²", ""):
                with self.subTest(port=port), patch(
                    "eml_viewer.services.settings_service.get_suite_common_fallback",
                    side_effect=lambda key, default: port if key == "SMTPPort" else default,
                ):
                    self.assertEqual(service.load_settings().smtp_port, 25)

    def test_failed_atomic_replace_preserves_original_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            service = SettingsService(path)
            service.save_settings(AppSettings(language="en", smtp_port=25))
            original = path.read_bytes()
            with patch.object(Path, "replace", side_effect=PermissionError("locked")) as replace_file, patch(
                "eml_viewer.services.settings_service.time.sleep",
            ):
                with self.assertRaises(PermissionError):
                    service.save_settings(AppSettings(language="ko", smtp_port=587))
            self.assertEqual(replace_file.call_count, 3)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_failed_temp_flush_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            service = SettingsService(path)
            service.save_settings(AppSettings(language="en"))
            original = path.read_bytes()
            with patch("eml_viewer.services.settings_service.os.fsync", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    service.save_settings(AppSettings(language="ko"))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_failed_initial_save_does_not_create_partial_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            with patch.object(Path, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    SettingsService(path).save_settings(AppSettings())
            self.assertFalse(path.exists())
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_transient_lock_retries_with_the_same_complete_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            original_replace = Path.replace
            sources: list[Path] = []
            def replace_after_lock(source, target):
                sources.append(source)
                if len(sources) == 1:
                    raise PermissionError("temporary lock")
                return original_replace(source, target)
            with patch.object(Path, "replace", replace_after_lock), patch(
                "eml_viewer.services.settings_service.time.sleep",
            ):
                SettingsService(path).save_settings(AppSettings(language="en"))
            self.assertEqual(len(sources), 2)
            self.assertEqual(sources[0], sources[1])
            self.assertEqual(SettingsService(path).load_settings().language, "en")
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_saves_use_unique_temp_names_in_the_settings_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "설정 폴더 ż" / "settings.json"
            original_replace = Path.replace
            sources: list[Path] = []
            def record_replace(source, target):
                sources.append(source)
                return original_replace(source, target)
            with patch.object(Path, "replace", record_replace):
                service = SettingsService(path)
                service.save_settings(AppSettings(language="en"))
                service.save_settings(AppSettings(language="ko"))
            self.assertNotEqual(sources[0], sources[1])
            self.assertTrue(all(source.parent == path.parent for source in sources))
            self.assertEqual(service.load_settings().language, "ko")

    def test_save_and_load_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            service = SettingsService(settings_path)
            expected = AppSettings(
                window_x=10,
                window_y=20,
                window_width=800,
                window_height=600,
                language="en",
                theme="dark",
                auto_load_remote_images=True,
                smtp_host="smtp.example.com",
                smtp_sender="sender@example.com",
                smtp_port=2525,
                recent_recipients=("one@example.com, two@example.com",),
            )

            service.save_settings(expected)
            actual = service.load_settings()

            self.assertEqual(actual, expected)

    def test_invalid_settings_file_returns_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text("{invalid json", encoding="utf-8")

            actual = SettingsService(settings_path).load_settings()

            self.assertEqual(actual, AppSettings())

    def test_window_geometry_save_preserves_language_and_theme(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            service = SettingsService(settings_path)
            service.save_settings(
                AppSettings(
                    language="en",
                    theme="dark",
                    auto_load_remote_images=True,
                    smtp_host="smtp.example.com",
                    smtp_sender="sender@example.com",
                    smtp_port=2525,
                )
            )

            service.save_window_geometry(x=1, y=2, width=3, height=4)
            actual = service.load_settings()

            self.assertEqual(actual.language, "en")
            self.assertEqual(actual.theme, "dark")
            self.assertTrue(actual.auto_load_remote_images)
            self.assertEqual(actual.smtp_host, "smtp.example.com")
            self.assertEqual(actual.smtp_sender, "sender@example.com")
            self.assertEqual(actual.smtp_port, 2525)
            self.assertEqual(actual.window_x, 1)
            self.assertEqual(actual.window_height, 4)

    def test_invalid_language_and_theme_fall_back_to_defaults(self) -> None:
        actual = AppSettings.from_dict({"language": "bad", "theme": "bad"})

        self.assertEqual(actual.language, "ko")
        self.assertEqual(actual.theme, "system")

    def test_invalid_smtp_port_falls_back_to_default(self) -> None:
        actual = AppSettings.from_dict({"smtp_port": 999999})

        self.assertEqual(actual.smtp_port, 25)

    def test_auto_load_remote_images_defaults_to_false(self) -> None:
        actual = AppSettings.from_dict({})

        self.assertFalse(actual.auto_load_remote_images)

    def test_auto_load_remote_images_accepts_boolean_like_values(self) -> None:
        self.assertTrue(AppSettings.from_dict({"auto_load_remote_images": True}).auto_load_remote_images)
        self.assertTrue(AppSettings.from_dict({"auto_load_remote_images": "true"}).auto_load_remote_images)
        self.assertFalse(AppSettings.from_dict({"auto_load_remote_images": "false"}).auto_load_remote_images)

    def test_save_recent_recipients_keeps_newest_ten_unique_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SettingsService(Path(temp_dir) / "settings.json")
            recipients = [f"person{index}@example.com" for index in range(12)]

            service.save_recent_recipients([recipients[0], recipients[0].upper(), *recipients[1:]])

            self.assertEqual(service.load_settings().recent_recipients, tuple(recipients[:10]))

    def test_add_recent_file_keeps_newest_ten_unique_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SettingsService(Path(temp_dir) / "settings.json")
            files = [str(Path(temp_dir) / f"mail_{i}.eml") for i in range(15)]

            for f in files:
                service.add_recent_file(f)

            recent = service.load_settings().recent_files
            self.assertEqual(len(recent), 10)
            # 가장 최근에 추가된 항목이 맨 앞이어야 함
            self.assertEqual(recent[0], files[-1])

            # 중복 추가 시 맨 앞으로 이동하고 개수는 유지
            service.add_recent_file(files[10])
            recent_updated = service.load_settings().recent_files
            self.assertEqual(len(recent_updated), 10)
            self.assertEqual(recent_updated[0], files[10])

    def test_startup_and_tray_settings_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SettingsService(Path(temp_dir) / "settings.json")
            settings = AppSettings(
                startup_with_windows=True,
                minimize_to_tray_on_close=False,
            )
            service.save_settings(settings)
            loaded = service.load_settings()
            self.assertTrue(loaded.startup_with_windows)
            self.assertFalse(loaded.minimize_to_tray_on_close)


if __name__ == "__main__":
    unittest.main()
