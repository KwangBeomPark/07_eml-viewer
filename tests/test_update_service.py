from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eml_viewer.services.update_service import UpdateCheckError, UpdateCheckResult, UpdateService


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class UpdateServiceTest(unittest.TestCase):
    def test_update_available_uses_installer_asset(self) -> None:
        payload = {
            "tag_name": "v0.2.0",
            "html_url": "https://github.com/KwangBeomPark/eml-viewer/releases/tag/v0.2.0",
            "assets": [
                {
                    "name": "EmlViewerSetup-0.2.0.exe",
                    "browser_download_url": "https://example.com/EmlViewerSetup-0.2.0.exe",
                    "size": 12345,
                }
            ],
        }

        service = UpdateService(current_version="0.1.0", opener=lambda request, timeout: FakeResponse(payload))
        result = service.check_for_updates()

        self.assertTrue(result.update_available)
        self.assertEqual(result.latest_version, "0.2.0")
        self.assertEqual(result.download_url, "https://example.com/EmlViewerSetup-0.2.0.exe")
        self.assertEqual(result.asset_name, "EmlViewerSetup-0.2.0.exe")
        self.assertEqual(result.asset_size, 12345)

    def test_update_available_uses_app07_installer_asset(self) -> None:
        payload = {
            "tag_name": "v0.2.0",
            "html_url": "https://github.com/KwangBeomPark/eml-viewer/releases/tag/v0.2.0",
            "assets": [
                {
                    "name": "App07_EmlViewer_Setup_v0.2.0.exe",
                    "browser_download_url": "https://example.com/App07_EmlViewer_Setup_v0.2.0.exe",
                    "size": 54321,
                }
            ],
        }

        service = UpdateService(current_version="0.1.0", opener=lambda request, timeout: FakeResponse(payload))
        result = service.check_for_updates()

        self.assertTrue(result.update_available)
        self.assertEqual(result.latest_version, "0.2.0")
        self.assertEqual(result.download_url, "https://example.com/App07_EmlViewer_Setup_v0.2.0.exe")
        self.assertEqual(result.asset_name, "App07_EmlViewer_Setup_v0.2.0.exe")
        self.assertEqual(result.asset_size, 54321)

    def test_same_version_is_latest(self) -> None:
        payload = {
            "tag_name": "v0.1.0",
            "html_url": "https://github.com/KwangBeomPark/eml-viewer/releases/tag/v0.1.0",
            "assets": [],
        }

        service = UpdateService(current_version="0.1.0", opener=lambda request, timeout: FakeResponse(payload))
        result = service.check_for_updates()

        self.assertFalse(result.update_available)

    def test_network_error_becomes_user_level_error(self) -> None:
        def failing_opener(request, timeout):
            raise urllib.error.URLError("offline")

        service = UpdateService(current_version="0.1.0", opener=failing_opener)

        with self.assertRaises(UpdateCheckError):
            service.check_for_updates()

    def test_missing_latest_release_has_actionable_message(self) -> None:
        def failing_opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", None, None)

        service = UpdateService(current_version="0.1.0", opener=failing_opener)

        with self.assertRaises(UpdateCheckError) as context:
            service.check_for_updates()

        self.assertIn("배포 정보를 찾을 수 없습니다", str(context.exception))

    def test_unexpected_payload_shape_becomes_user_level_error(self) -> None:
        service = UpdateService(current_version="0.1.0", opener=lambda request, timeout: FakeResponse([]))

        with self.assertRaises(UpdateCheckError):
            service.check_for_updates()

    def test_cached_installer_is_valid_when_asset_size_matches(self) -> None:
        service = UpdateService(current_version="0.1.0", opener=lambda request, timeout: FakeResponse({}))
        update = UpdateCheckResult(
            current_version="0.1.0",
            latest_version="0.2.0",
            release_url="https://example.com",
            download_url="https://example.com/EmlViewerSetup-0.2.0.exe",
            asset_name="EmlViewerSetup-0.2.0.exe",
            asset_size=3,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = service.installer_cache_path(update, temp_dir)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(b"abc")

            self.assertTrue(service.has_valid_cached_installer(update, temp_dir))

            cache_path.write_bytes(b"abcd")
            self.assertFalse(service.has_valid_cached_installer(update, temp_dir))


if __name__ == "__main__":
    unittest.main()
