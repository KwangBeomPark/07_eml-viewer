from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from eml_viewer.app_identity import (
    CONFIG_FILENAME,
    get_suite_common_fallback,
    legacy_roaming_settings_path,
    user_data_dir,
)
from eml_viewer.models.app_settings import AppSettings


def _move_windows_no_replace(source: Path, destination: Path) -> None:
    """Publish a complete sibling file without replacing a concurrent target."""
    import ctypes
    from ctypes import wintypes

    move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileW
    move.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    move.restype = wintypes.BOOL
    if not move(str(source), str(destination)):
        error = ctypes.get_last_error()
        if error in (80, 183):
            raise FileExistsError(
                error, "Settings destination already exists", str(destination)
            )
        raise ctypes.WinError(error)


class SettingsService:
    """창 크기와 위치 같은 사용자 설정을 JSON 파일에 저장합니다.
    PL Suite storage convention 및 00_Registry 레지스트리 표준을 준수합니다.
    """

    def __init__(self, settings_path: str | Path | None = None, auto_migrate: bool | None = None) -> None:
        self.settings_path = Path(settings_path) if settings_path else self.default_settings_path()
        should_migrate = auto_migrate if auto_migrate is not None else (settings_path is None)
        if should_migrate:
            self._ensure_migrated()

    def _ensure_migrated(self) -> None:
        """Validate a complete legacy copy before publishing to an absent target."""
        if self.settings_path.exists():
            return
        legacy_path = legacy_roaming_settings_path()
        if legacy_path != self.settings_path and legacy_path.exists() and legacy_path.is_file():
            staged: Path | None = None
            try:
                def identity():
                    stat = legacy_path.stat()
                    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

                source_identity = identity()
                source_bytes = legacy_path.read_bytes()
                if identity() != source_identity:
                    raise OSError("Legacy settings changed while being read.")
                if not isinstance(json.loads(source_bytes.decode("utf-8")), dict):
                    raise ValueError("Legacy settings must be a JSON object.")
                self.settings_path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    dir=self.settings_path.parent, prefix=f"{self.settings_path.name}.migration.",
                    suffix=".tmp", delete=False,
                ) as stream:
                    staged = Path(stream.name)
                shutil.copyfile(legacy_path, staged)
                with staged.open("rb+") as stream:
                    os.fsync(stream.fileno())
                if staged.read_bytes() != source_bytes:
                    raise OSError("Legacy settings copy did not match the original.")
                if identity() != source_identity or legacy_path.read_bytes() != source_bytes:
                    raise OSError("Legacy settings changed during migration.")
                try:
                    # Hard-link publication is atomic and never replaces a raced target.
                    os.link(staged, self.settings_path)
                except FileExistsError:
                    return
                except OSError:
                    # Fallback for filesystems that do not support hard links (e.g., FAT32, exFAT).
                    # Atomically publish without overwriting if target was created concurrently.
                    if sys.platform == "win32":
                        try:
                            _move_windows_no_replace(staged, self.settings_path)
                        except FileExistsError:
                            return
                        staged = None
                        return
                    else:
                        # On POSIX filesystems without hard-link support, reject non-atomic publication
                        # to prevent exposing incomplete files or corrupted targets.
                        raise OSError("Hard-link publication unsupported; atomic migration unavailable.")
            except (OSError, ValueError, UnicodeError) as exc:
                raise OSError(
                    "Settings migration failed. The original was kept; check permissions and retry."
                ) from exc
            finally:
                if staged is not None:
                    try:
                        staged.unlink(missing_ok=True)
                    except OSError:
                        pass

    def load_settings(self) -> AppSettings:
        saved_keys: set[str] = set()
        if not self.settings_path.exists():
            loaded = AppSettings()
        else:
            try:
                data = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    loaded = AppSettings()
                else:
                    loaded = AppSettings.from_dict(data)
                    saved_keys = set(data)
            except Exception:
                loaded = AppSettings()

        return self._apply_suite_fallbacks(loaded, saved_keys)

    def _apply_suite_fallbacks(self, settings: AppSettings, saved_keys: set[str]) -> AppSettings:
        """사용자 명시 설정이 없을 때 00_Registry PL_Suite\\Common 기본값을 fallback으로 적용."""
        updates: dict[str, object] = {}
        if "smtp_host" not in saved_keys:
            suite_smtp = get_suite_common_fallback("SMTPServer", "")
            if suite_smtp:
                updates["smtp_host"] = suite_smtp

        if "smtp_port" not in saved_keys:
            suite_port = get_suite_common_fallback("SMTPPort", "")
            if suite_port and suite_port.isascii() and suite_port.isdigit():
                port = int(suite_port)
                if 1 <= port <= 65535:
                    updates["smtp_port"] = port

        if updates:
            return replace(settings, **updates)
        return settings

    def _assert_existing_settings_readable(self) -> None:
        """Prevent fallback defaults from overwriting a damaged original file."""
        try:
            content = self.settings_path.read_text(encoding="utf-8")
            if not isinstance(json.loads(content), dict):
                raise ValueError("Settings must be a JSON object")
        except FileNotFoundError:
            return
        except (ValueError, UnicodeError) as exc:
            raise OSError(
                "Existing settings are damaged. Keep a backup and repair the file before saving."
            ) from exc

    def save_settings(self, settings: AppSettings) -> None:
        """원자적(Atomic) 파일 저장 기법을 적용하여 정전 또는 비정상 종료 시 손상을 방지합니다."""
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._assert_existing_settings_readable()
        content = json.dumps(settings.to_dict(), indent=2, ensure_ascii=False)
        temp_file: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.settings_path.parent,
                prefix=f"{self.settings_path.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temp_file = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            for attempt in range(3):
                try:
                    self._assert_existing_settings_readable()
                    temp_file.replace(self.settings_path)
                    return
                except PermissionError:
                    if attempt == 2:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        finally:
            if temp_file is not None:
                try:
                    temp_file.unlink(missing_ok=True)
                except OSError:
                    pass

    def save_window_geometry(self, x: int, y: int, width: int, height: int) -> None:
        current = self.load_settings()
        self.save_settings(
            replace(
                current,
                window_x=x,
                window_y=y,
                window_width=width,
                window_height=height,
            )
        )

    def save_recent_recipients(self, recipients: Sequence[str]) -> None:
        current = self.load_settings()
        cleaned = AppSettings._safe_recent_recipients(list(recipients))
        self.save_settings(replace(current, recent_recipients=cleaned))

    def add_recent_file(self, file_path: str | Path) -> AppSettings:
        current = self.load_settings()
        path_str = str(Path(file_path).resolve())
        new_list = [path_str] + [f for f in current.recent_files if f.casefold() != path_str.casefold()]
        cleaned = AppSettings._safe_recent_files(new_list)
        updated = replace(current, recent_files=cleaned)
        self.save_settings(updated)
        return updated

    @staticmethod
    def default_settings_path() -> Path:
        return user_data_dir() / CONFIG_FILENAME
