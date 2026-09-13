from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from eml_viewer import __version__
from eml_viewer.gui.i18n import tr


class UpdateCheckError(Exception):
    """업데이트 정보를 가져올 수 없을 때 사용하는 오류입니다."""


class UpdateDownloadError(Exception):
    """업데이트 설치 파일을 다운로드할 수 없을 때 사용하는 오류입니다."""


class OperationCanceled(Exception):
    """사용자가 작업을 취소했을 때 발생하는 예외입니다."""


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str
    release_url: str
    download_url: str | None
    asset_name: str = ""
    asset_size: int = 0

    @property
    def update_available(self) -> bool:
        return _version_tuple(self.latest_version) > _version_tuple(self.current_version)


class UpdateService:
    """GitHub Releases에서 최신 설치 파일 정보를 확인합니다."""

    def __init__(
        self,
        repository: str = "KwangBeomPark/eml-viewer",
        current_version: str = __version__,
        timeout_seconds: int = 10,
        download_timeout_seconds: int = 300,
        opener=None,
    ) -> None:
        self._repository = repository
        self._current_version = current_version
        self._timeout_seconds = timeout_seconds
        self._download_timeout_seconds = download_timeout_seconds
        self._opener = opener or urllib.request.urlopen

    def check_for_updates(self) -> UpdateCheckResult:
        url = f"https://api.github.com/repos/{self._repository}/releases/latest"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "EML-Viewer-Update-Checker",
            },
        )

        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise UpdateCheckError(tr("update.no_release")) from exc
            raise UpdateCheckError(tr("update.request_failed", code=exc.code)) from exc
        except Exception as exc:
            raise UpdateCheckError(tr("update.request_failed_connection")) from exc

        if not isinstance(payload, dict):
            raise UpdateCheckError(tr("update.read_failed"))

        latest_version = _normalize_version(str(payload.get("tag_name", "")))
        if not latest_version:
            raise UpdateCheckError(tr("update.read_failed"))

        release_url = str(payload.get("html_url", ""))
        installer_asset = self._installer_download_asset(payload)
        download_url = (installer_asset.get("download_url") if installer_asset else None) or release_url or None

        return UpdateCheckResult(
            current_version=self._current_version,
            latest_version=latest_version,
            release_url=release_url,
            download_url=download_url,
            asset_name=str(installer_asset.get("name", "")) if installer_asset else "",
            asset_size=int(installer_asset.get("size", 0)) if installer_asset else 0,
        )

    def _installer_download_url(self, payload: dict) -> str | None:
        asset = self._installer_download_asset(payload)
        return str(asset.get("download_url", "")) if asset else None

    def _installer_download_asset(self, payload: dict) -> dict[str, str | int] | None:
        assets = payload.get("assets", [])
        if not isinstance(assets, list):
            return None

        # 1. Prefer modern standard naming (App07_EmlViewer_Setup_*.exe)
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name", ""))
            if name.startswith("App07_EmlViewer_Setup_") and name.lower().endswith(".exe"):
                return {
                    "name": name,
                    "download_url": str(asset.get("browser_download_url", "")),
                    "size": _safe_int(asset.get("size", 0)),
                }

        # 2. Fallback to legacy naming (EmlViewerSetup-*.exe)
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name", ""))
            if name.startswith("EmlViewerSetup-") and name.lower().endswith(".exe"):
                return {
                    "name": name,
                    "download_url": str(asset.get("browser_download_url", "")),
                    "size": _safe_int(asset.get("size", 0)),
                }
        return None

    def installer_cache_path(self, result: UpdateCheckResult, cache_dir: str | Path | None = None) -> Path:
        filename = result.asset_name.strip() or _filename_from_url(result.download_url or "") or "EmlViewerSetup.exe"
        root = Path(cache_dir) if cache_dir is not None else Path(tempfile.gettempdir()) / "EmlViewerUpdates"
        return root / filename

    def has_valid_cached_installer(self, result: UpdateCheckResult, cache_dir: str | Path | None = None) -> bool:
        path = self.installer_cache_path(result, cache_dir)
        if not path.exists() or not path.is_file():
            return False
        if result.asset_size <= 0:
            return path.stat().st_size > 0
        return path.stat().st_size == result.asset_size

    def download_installer(
        self,
        url: str,
        dest_path: str,
        progress_callback=None,
        cancel_event=None,
    ) -> None:
        """설치 프로그램을 다운로드합니다."""
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "EML-Viewer-Updater",
            },
        )
        destination = Path(dest_path)
        temp_path: Path | None = None

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with self._opener(request, timeout=self._download_timeout_seconds) as response:
                total_size = int(response.headers.get("content-length", 0))
                block_size = 8192
                downloaded = 0

                fd, temp_name = tempfile.mkstemp(
                    prefix=f".{destination.name}.",
                    suffix=".tmp",
                    dir=destination.parent,
                )
                temp_path = Path(temp_name)
                with os.fdopen(fd, "wb") as f:
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            raise OperationCanceled(tr("update.download.canceled"))

                        buffer = response.read(block_size)
                        if not buffer:
                            break

                        f.write(buffer)
                        downloaded += len(buffer)

                        if progress_callback is not None:
                            progress_callback(downloaded, total_size)

                if downloaded == 0:
                    raise UpdateDownloadError(tr("update.download_empty"))

                os.replace(temp_path, destination)
                temp_path = None
        except Exception as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            if isinstance(exc, OperationCanceled):
                raise
            if isinstance(exc, UpdateDownloadError):
                raise
            raise UpdateDownloadError(tr("update.download_error", error=exc)) from exc


def _normalize_version(version: str) -> str:
    return version.strip().lstrip("vV")


def _version_tuple(version: str) -> tuple[int, ...]:
    normalized = _normalize_version(version)
    parts: list[int] = []
    for part in normalized.split("."):
        digits = "".join(char for char in part if char.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _filename_from_url(url: str) -> str:
    if not url:
        return ""
    return url.split("/")[-1].split("?")[0]
