from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppSettings:
    """프로그램 창 위치와 크기를 저장하는 데이터입니다."""

    window_x: int = 100
    window_y: int = 100
    window_width: int = 1100
    window_height: int = 760
    language: str = "ko"
    theme: str = "system"
    auto_load_remote_images: bool = False
    smtp_host: str = ""
    smtp_sender: str = ""
    smtp_port: int = 25
    recent_recipients: tuple[str, ...] = ()
    recent_files: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        language = str(data.get("language", cls.language))
        if language not in {"ko", "en"}:
            language = cls.language

        theme = str(data.get("theme", cls.theme))
        if theme not in {"system", "light", "dark"}:
            theme = cls.theme

        return cls(
            window_x=int(data.get("window_x", cls.window_x)),
            window_y=int(data.get("window_y", cls.window_y)),
            window_width=int(data.get("window_width", cls.window_width)),
            window_height=int(data.get("window_height", cls.window_height)),
            language=language,
            theme=theme,
            auto_load_remote_images=cls._safe_bool(
                data.get("auto_load_remote_images", cls.auto_load_remote_images)
            ),
            smtp_host=str(data.get("smtp_host", cls.smtp_host)).strip(),
            smtp_sender=str(data.get("smtp_sender", cls.smtp_sender)).strip(),
            smtp_port=cls._safe_port(data.get("smtp_port", cls.smtp_port)),
            recent_recipients=cls._safe_recent_recipients(data.get("recent_recipients", ())),
            recent_files=cls._safe_recent_files(data.get("recent_files", ())),
        )

    def to_dict(self) -> dict[str, bool | int | str | list[str]]:
        return {
            "window_x": self.window_x,
            "window_y": self.window_y,
            "window_width": self.window_width,
            "window_height": self.window_height,
            "language": self.language,
            "theme": self.theme,
            "auto_load_remote_images": self.auto_load_remote_images,
            "smtp_host": self.smtp_host,
            "smtp_sender": self.smtp_sender,
            "smtp_port": self.smtp_port,
            "recent_recipients": list(self.recent_recipients),
            "recent_files": list(self.recent_files),
        }

    @staticmethod
    def _safe_port(value: object) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError):
            return AppSettings.smtp_port
        return port if 1 <= port <= 65535 else AppSettings.smtp_port

    @staticmethod
    def _safe_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def _safe_recent_recipients(value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()

        recipients: list[str] = []
        seen: set[str] = set()
        for item in value:
            recipient = str(item).strip()
            key = recipient.casefold()
            if not recipient or key in seen:
                continue
            seen.add(key)
            recipients.append(recipient)
            if len(recipients) == 10:
                break
        return tuple(recipients)

    @staticmethod
    def _safe_recent_files(value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()

        files: list[str] = []
        seen: set[str] = set()
        for item in value:
            file_path = str(item).strip()
            key = file_path.casefold()
            if not file_path or key in seen:
                continue
            seen.add(key)
            files.append(file_path)
            if len(files) == 10:
                break
        return tuple(files)
