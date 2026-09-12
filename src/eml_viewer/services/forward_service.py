from __future__ import annotations

import smtplib
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path

from eml_viewer.gui.i18n import tr
from eml_viewer.models.app_settings import AppSettings
from eml_viewer.models.email_data import ParsedEmail


class ForwardConfigError(Exception):
    """Raised when SMTP forwarding settings are incomplete."""


class ForwardSendError(Exception):
    """Raised when the current email cannot be forwarded."""


class ForwardService:
    """Sends the current message body and attaches the original email file."""

    def __init__(self, smtp_factory=smtplib.SMTP) -> None:
        self._smtp_factory = smtp_factory

    def forward_email(self, email: ParsedEmail, settings: AppSettings, recipient: str) -> str:
        recipient = self._normalize_recipients(recipient)
        self._validate_settings(settings, recipient)

        if email.source_path is None:
            raise ForwardSendError(tr("forward.error.no_email"))

        source_path = Path(email.source_path)
        try:
            original_bytes = source_path.read_bytes()
        except OSError as exc:
            raise ForwardSendError(tr("forward.error.read_original", source_path=source_path)) from exc

        message = EmailMessage()
        message["From"] = settings.smtp_sender
        message["To"] = recipient
        message["Subject"] = self._forward_subject(email.subject)
        message.set_content(self._plain_forward_body(email))
        self._add_html_body(message, email)
        self._attach_original(message, original_bytes, source_path)

        try:
            with self._smtp_factory(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                smtp.send_message(message)
        except Exception as exc:
            raise ForwardSendError(tr("forward.error.send", error=exc)) from exc
        return recipient

    def _attach_original(self, message: EmailMessage, original_bytes: bytes, source_path: Path) -> None:
        if source_path.suffix.lower() == ".msg":
            message.add_attachment(
                original_bytes,
                maintype="application",
                subtype="vnd.ms-outlook",
                filename=source_path.name,
            )
            return

        try:
            original = message_from_bytes(original_bytes, policy=policy.default)
            probe = EmailMessage()
            probe.add_attachment(original, filename=source_path.name)
            probe.as_bytes()
        except Exception:
            # A malformed original may not survive re-serialization as a nested
            # message/rfc822 part; deliver the raw bytes as a plain file instead.
            message.add_attachment(
                original_bytes,
                maintype="application",
                subtype="octet-stream",
                filename=source_path.name,
            )
            return
        message.add_attachment(original, filename=source_path.name)

    def _validate_settings(self, settings: AppSettings, recipient: str) -> None:
        missing: list[str] = []
        if not settings.smtp_host.strip():
            missing.append(tr("settings.smtp_host"))
        if not settings.smtp_sender.strip():
            missing.append(tr("settings.smtp_sender"))
        if not recipient:
            missing.append(tr("forward.recipient_prompt").rstrip(":"))
        if missing:
            raise ForwardConfigError(tr("forward.missing_prefix", fields=", ".join(missing)))

    def _forward_subject(self, subject: str) -> str:
        subject = subject.strip()
        if not subject:
            return "Fwd: forwarded EML"
        if subject.lower().startswith(("fw:", "fwd:")):
            return subject
        return f"Fwd: {subject}"

    def _plain_forward_body(self, email: ParsedEmail) -> str:
        body = email.plain_body.strip() or "(Plain text body is not available.)"
        return (
            "Forwarded from EML Viewer.\n\n"
            "----- Original message -----\n"
            f"Subject: {email.subject}\n"
            f"From: {email.sender}\n"
            f"To: {email.recipients}\n"
            f"Date: {email.date}\n\n"
            f"{body}\n"
        )

    def _add_html_body(self, message: EmailMessage, email: ParsedEmail) -> None:
        html_body = email.html_body.strip()
        if not html_body:
            return

        message.add_alternative(html_body, subtype="html")
        html_part = message.get_payload()[-1]
        for index, resource in enumerate(email.inline_resources, start=1):
            maintype, subtype = self._mime_parts(resource.content_type)
            content_id = resource.content_id.strip() or f"inline-{index}"
            html_part.add_related(
                resource.payload,
                maintype=maintype,
                subtype=subtype,
                cid=f"<{content_id}>",
                filename=resource.filename or None,
                disposition="inline",
            )
            if resource.content_location:
                html_part.get_payload()[-1]["Content-Location"] = resource.content_location

    def _mime_parts(self, content_type: str) -> tuple[str, str]:
        media_type = content_type.split(";", 1)[0].strip().lower()
        maintype, separator, subtype = media_type.partition("/")
        if not separator or not maintype or not subtype:
            return "application", "octet-stream"
        return maintype, subtype

    def _normalize_recipients(self, recipients: str) -> str:
        normalized: list[str] = []
        seen: set[str] = set()
        for recipient in recipients.split(","):
            cleaned = recipient.strip()
            key = cleaned.casefold()
            if not cleaned or key in seen:
                continue
            seen.add(key)
            normalized.append(cleaned)
        return ", ".join(normalized)
