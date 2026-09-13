from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eml_viewer.gui.i18n import tr
from eml_viewer.models.attachment_data import AttachmentInfo
from eml_viewer.services.eml_parser import EmlParser
from eml_viewer.services.file_operation_service import FileOperationPreview, FileOperationService


@dataclass(frozen=True)
class AttachmentSaveResult:
    attachment: AttachmentInfo
    path: Path


class AttachmentService:
    """첨부파일 저장 기능을 담당합니다."""

    def __init__(
        self,
        parser: EmlParser | None = None,
        file_operation_service: FileOperationService | None = None,
    ) -> None:
        self._parser = parser or EmlParser()
        self._file_operation_service = file_operation_service or FileOperationService()

    def create_save_preview(
        self,
        attachment: AttachmentInfo,
        destination_path: str | Path,
    ) -> FileOperationPreview:
        return self._file_operation_service.build_write_preview(
            source_label=tr("attachment.source_label", filename=attachment.filename),
            destination_path=destination_path,
            action="save_attachment",
        )

    def save_attachment(
        self,
        email_path: str | Path,
        attachment_index: int,
        destination_path: str | Path,
        overwrite: bool = False,
        apply_motw: bool = True,
    ) -> Path:
        extracted = self._parser.extract_attachment(email_path, attachment_index)
        return self._file_operation_service.write_bytes(
            destination_path=destination_path,
            data=extracted.payload,
            overwrite=overwrite,
            apply_motw=apply_motw,
        )

    def create_bulk_save_preview(
        self,
        attachments: list[AttachmentInfo],
        destination_dir: str | Path,
    ) -> list[FileOperationPreview]:
        return [
            self._file_operation_service.build_write_preview(
                source_label=tr("attachment.source_label", filename=attachment.filename),
                destination_path=destination,
                action="save_attachment",
            )
            for attachment, destination in self._bulk_destinations(attachments, destination_dir)
        ]

    def save_attachments(
        self,
        email_path: str | Path,
        attachments: list[AttachmentInfo],
        destination_dir: str | Path,
        overwrite: bool = False,
    ) -> list[AttachmentSaveResult]:
        results: list[AttachmentSaveResult] = []
        for attachment, destination in self._bulk_destinations(attachments, destination_dir):
            saved_path = self.save_attachment(
                email_path=email_path,
                attachment_index=attachment.index,
                destination_path=destination,
                overwrite=overwrite,
            )
            results.append(AttachmentSaveResult(attachment=attachment, path=saved_path))
        return results

    def _bulk_destinations(
        self,
        attachments: list[AttachmentInfo],
        destination_dir: str | Path,
    ) -> list[tuple[AttachmentInfo, Path]]:
        destination_root = Path(destination_dir)
        used_names: set[str] = set()
        destinations: list[tuple[AttachmentInfo, Path]] = []
        for attachment in attachments:
            safe_filename = self._file_operation_service.sanitize_filename(attachment.filename)
            unique_filename = self._unique_filename(safe_filename, used_names)
            used_names.add(unique_filename.lower())
            destinations.append((attachment, destination_root / unique_filename))
        return destinations

    def _unique_filename(self, filename: str, used_names: set[str]) -> str:
        candidate = filename
        path = Path(filename)
        stem = path.stem or "attachment"
        suffix = path.suffix
        counter = 2
        while candidate.lower() in used_names:
            candidate = f"{stem} ({counter}){suffix}"
            counter += 1
        return candidate
