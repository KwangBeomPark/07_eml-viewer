from __future__ import annotations

import json
import os
import shutil
import sys
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
        """기존 %APPDATA%/EmlViewer/settings.json 설정이 있고 새 경로에 없으면 1회 비파괴적 복사."""
        if self.settings_path.exists():
            return
        legacy_path = legacy_roaming_settings_path()
        if legacy_path != self.settings_path and legacy_path.exists() and legacy_path.is_file():
            try:
                self.settings_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy_path, self.settings_path)
            except OSError:
                pass

    def load_settings(self) -> AppSettings:
        if not self.settings_path.exists():
            loaded = AppSettings()
        else:
            try:
                data = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    loaded = AppSettings()
                else:
                    loaded = AppSettings.from_dict(data)
            except Exception:
                loaded = AppSettings()

        return self._apply_suite_fallbacks(loaded)

    def _apply_suite_fallbacks(self, settings: AppSettings) -> AppSettings:
        """사용자 명시 설정이 없을 때 00_Registry PL_Suite\\Common 기본값을 fallback으로 적용."""
        updates: dict[str, object] = {}
        if not settings.smtp_host:
            suite_smtp = get_suite_common_fallback("SMTPServer", "")
            if suite_smtp:
                updates["smtp_host"] = suite_smtp

        if settings.smtp_port == 25:
            suite_port = get_suite_common_fallback("SMTPPort", "")
            if suite_port and suite_port.isdigit():
                updates["smtp_port"] = int(suite_port)

        if updates:
            return replace(settings, **updates)
        return settings

    def save_settings(self, settings: AppSettings) -> None:
        """원자적(Atomic) 파일 저장 기법을 적용하여 정전 또는 비정상 종료 시 손상을 방지합니다."""
        import time

        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(settings.to_dict(), indent=2, ensure_ascii=False)
        temp_file = self.settings_path.with_name(f"{self.settings_path.name}.{os.getpid()}.tmp")
        try:
            temp_file.write_text(content, encoding="utf-8")
            last_err: Exception | None = None
            for attempt in range(3):
                try:
                    temp_file.replace(self.settings_path)
                    return
                except PermissionError as err:
                    last_err = err
                    time.sleep(0.05 * (attempt + 1))
            if last_err:
                raise last_err
        except Exception:
            self.settings_path.write_text(content, encoding="utf-8")
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
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
