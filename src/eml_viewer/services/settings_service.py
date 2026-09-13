from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from collections.abc import Sequence

from eml_viewer.models.app_settings import AppSettings


class SettingsService:
    """창 크기와 위치 같은 사용자 설정을 JSON 파일에 저장합니다."""

    def __init__(self, settings_path: str | Path | None = None) -> None:
        self.settings_path = Path(settings_path) if settings_path else self.default_settings_path()

    def load_settings(self) -> AppSettings:
        if not self.settings_path.exists():
            return AppSettings()

        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return AppSettings()
            return AppSettings.from_dict(data)
        except Exception:
            return AppSettings()

    def save_settings(self, settings: AppSettings) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps(settings.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

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
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
            return base / "EmlViewer" / "settings.json"
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "EmlViewer" / "settings.json"
        return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "EmlViewer" / "settings.json"
