import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eml_viewer.services.attachment_policy import DANGEROUS_EXTENSIONS, is_dangerous_extension


class AttachmentPolicyTests(unittest.TestCase):
    def test_dangerous_extensions_detection(self) -> None:
        dangerous_samples = [
            "malware.exe",
            "script.bat",
            "cmd_runner.cmd",
            "run.ps1",
            "script.vbs",
            "script.vbe",
            "script.js",
            "script.jse",
            "script.wsf",
            "script.wsh",
            "macro.docm",
            "macro.dotm",
            "macro.xlsm",
            "macro.xll",
            "shortcut.lnk",
            "shortcut.scf",
            "app.appref-ms",
            "script.HTA",  # 대문자 테스트
        ]
        for name in dangerous_samples:
            with self.subTest(name=name):
                self.assertTrue(is_dangerous_extension(name), f"{name} should be recognized as dangerous")

    def test_safe_extensions_detection(self) -> None:
        safe_samples = [
            "document.pdf",
            "document.docx",
            "data.xlsx",
            "presentation.pptx",
            "image.png",
            "image.jpg",
            "text.txt",
            "archive.zip",
            "no_extension",
        ]
        for name in safe_samples:
            with self.subTest(name=name):
                self.assertFalse(is_dangerous_extension(name), f"{name} should not be recognized as dangerous")


if __name__ == "__main__":
    unittest.main()
