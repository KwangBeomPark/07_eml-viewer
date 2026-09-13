from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eml_viewer.services.file_operation_service import FileOperationService


class FileOperationServiceTest(unittest.TestCase):
    def test_build_write_preview_marks_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "existing.txt"
            destination.write_text("old", encoding="utf-8")

            preview = FileOperationService().build_write_preview("첨부파일: existing.txt", destination)

            self.assertTrue(preview.will_overwrite)
            self.assertIn("기존 파일을 덮어씁니다.", preview.message)

    def test_write_bytes_requires_overwrite_for_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "existing.txt"
            destination.write_text("old", encoding="utf-8")
            service = FileOperationService()

            with self.assertRaises(FileExistsError):
                service.write_bytes(destination, b"new")

            service.write_bytes(destination, b"new", overwrite=True)
            self.assertEqual(destination.read_bytes(), b"new")

    def test_write_bytes_rejects_directory_before_overwrite_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir)

            with self.assertRaises(IsADirectoryError):
                FileOperationService().write_bytes(destination, b"new")

    def test_sanitize_filename_replaces_windows_invalid_chars(self) -> None:
        filename = FileOperationService().sanitize_filename('bad:name*?.txt')

        self.assertEqual(filename, "bad_name__.txt")

    def test_sanitize_filename_avoids_windows_reserved_names(self) -> None:
        service = FileOperationService()

        self.assertEqual(service.sanitize_filename("CON"), "CON_")
        self.assertEqual(service.sanitize_filename("nul.txt"), "nul_.txt")

    def test_write_bytes_applies_motw_on_windows(self) -> None:
        import sys
        service = FileOperationService()
        with tempfile.TemporaryDirectory() as temp_dir:
            dest = Path(temp_dir) / "test_motw.txt"
            service.write_bytes(dest, b"hello motw", apply_motw=True)
            self.assertEqual(dest.read_bytes(), b"hello motw")

            if sys.platform == "win32":
                zone_stream = Path(f"{dest}:Zone.Identifier")
                try:
                    content = zone_stream.read_text(encoding="utf-8")
                    self.assertIn("ZoneId=3", content)
                except OSError:
                    # Non-NTFS or unsupported filesystem
                    pass

    def test_apply_motw_returns_false_on_non_windows(self) -> None:
        from unittest.mock import patch
        with patch("eml_viewer.services.file_operation_service.sys.platform", "linux"):
            result = FileOperationService.apply_mark_of_the_web("dummy.txt")
            self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
