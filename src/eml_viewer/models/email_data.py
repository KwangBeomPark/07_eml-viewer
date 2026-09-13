from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from eml_viewer.models.attachment_data import AttachmentInfo, InlineResource


@dataclass(frozen=True)
class ParsedEmail:
    """EML 파일 하나를 화면에 표시하기 좋은 형태로 정리한 데이터입니다."""

    subject: str
    sender: str
    recipients: str
    date: str
    plain_body: str
    html_body: str
    attachments: list[AttachmentInfo] = field(default_factory=list)
    inline_resources: list[InlineResource] = field(default_factory=list)
    source_path: Path | None = None
    plain_body_generated: bool = False
    cc: str = ""
    raw_headers: str = ""

    @property
    def has_html(self) -> bool:
        return bool(self.html_body.strip())

    @property
    def has_plain_text(self) -> bool:
        return bool(self.plain_body.strip())
