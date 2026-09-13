from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eml_viewer.models.app_settings import AppSettings
from eml_viewer.services.settings_service import SettingsService


class SettingsServiceTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
