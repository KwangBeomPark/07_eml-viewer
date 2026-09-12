from __future__ import annotations

import sys
import tempfile
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eml_viewer.models.app_settings import AppSettings
from eml_viewer.models.attachment_data import InlineResource
from eml_viewer.models.email_data import ParsedEmail
from eml_viewer.services.forward_service import ForwardConfigError, ForwardService


class FakeSmtp:
    sent_messages: list[object] = []
    init_args: tuple[str, int, int] | None = None

    def __init__(self, host: str, port: int, timeout: int) -> None:
        type(self).init_args = (host, port, timeout)

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def send_message(self, message) -> None:
        type(self).sent_messages.append(message)


class ForwardServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeSmtp.sent_messages = []
        FakeSmtp.init_args = None

    def test_forward_email_sends_original_eml_as_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "original.eml"
            source_path.write_bytes(b"From: sender@example.com\nSubject: Inner subject\n\nBody")
            email = ParsedEmail(
                subject="Hello",
                sender="sender@example.com",
                recipients="receiver@example.com",
                date="2026-06-27",
                plain_body="Body",
                html_body="",
                source_path=source_path,
            )
            settings = AppSettings(
                smtp_host="smtp.example.com",
                smtp_port=2525,
                smtp_sender="forwarder@example.com",
            )

            ForwardService(FakeSmtp).forward_email(email, settings, "target@example.com")

            self.assertEqual(FakeSmtp.init_args, ("smtp.example.com", 2525, 30))
            self.assertEqual(len(FakeSmtp.sent_messages), 1)
            message = FakeSmtp.sent_messages[0]
            self.assertEqual(message["From"], "forwarder@example.com")
            self.assertEqual(message["To"], "target@example.com")
            self.assertEqual(message["Subject"], "Fwd: Hello")
            self.assertTrue(message.is_multipart())

            serialized = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
            attached = next(part for part in serialized.walk() if part.get_content_type() == "message/rfc822")
            self.assertEqual(attached.get_filename(), "original.eml")
            self.assertNotEqual(attached.get("Content-Transfer-Encoding", "").lower(), "base64")
            inner = attached.get_content()
            if isinstance(inner, list):
                inner = inner[0]
            self.assertEqual(inner["Subject"], "Inner subject")

    def test_forward_email_attaches_msg_source_as_outlook_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "original.msg"
            msg_bytes = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1fake-ole-payload"
            source_path.write_bytes(msg_bytes)
            email = ParsedEmail(
                subject="Msg mail",
                sender="sender@example.com",
                recipients="receiver@example.com",
                date="2026-06-27",
                plain_body="Body",
                html_body="",
                source_path=source_path,
            )
            settings = AppSettings(
                smtp_host="smtp.example.com",
                smtp_port=2525,
                smtp_sender="forwarder@example.com",
            )

            ForwardService(FakeSmtp).forward_email(email, settings, "target@example.com")

            message = FakeSmtp.sent_messages[0]
            serialized = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
            attached = next(part for part in serialized.walk() if part.get_filename() == "original.msg")
            self.assertEqual(attached.get_content_type(), "application/vnd.ms-outlook")
            self.assertEqual(attached.get_content(), msg_bytes)

    def test_forward_email_requires_smtp_settings(self) -> None:
        email = ParsedEmail(
            subject="",
            sender="",
            recipients="",
            date="",
            plain_body="",
            html_body="",
        )

        with self.assertRaises(ForwardConfigError):
            ForwardService(FakeSmtp).forward_email(email, AppSettings(), "target@example.com")

    def test_forward_email_preserves_html_and_inline_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "original.eml"
            source_path.write_bytes(b"From: sender@example.com\n\nBody")
            email = ParsedEmail(
                subject="HTML mail",
                sender="sender@example.com",
                recipients="receiver@example.com",
                date="2026-06-27",
                plain_body="Plain body",
                html_body='<html><body><p>HTML body</p><img src="cid:chart@example"></body></html>',
                inline_resources=[
                    InlineResource(
                        content_id="chart@example",
                        filename="chart.png",
                        content_type="image/png",
                        payload=b"image-bytes",
                    )
                ],
                source_path=source_path,
            )
            settings = AppSettings(
                smtp_host="smtp.example.com",
                smtp_port=2525,
                smtp_sender="forwarder@example.com",
            )

            ForwardService(FakeSmtp).forward_email(email, settings, "target@example.com")

            message = FakeSmtp.sent_messages[0]
            serialized = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
            html_part = serialized.get_body(preferencelist=("html",))
            image_part = next(part for part in serialized.walk() if part.get("Content-ID") == "<chart@example>")

            self.assertIsNotNone(html_part)
            self.assertIn('src="cid:chart@example"', html_part.get_content())
            self.assertEqual(image_part.get_content(), b"image-bytes")
            self.assertEqual(image_part.get_content_disposition(), "inline")

    def test_forward_email_normalizes_comma_separated_recipients(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "original.eml"
            source_path.write_bytes(b"From: sender@example.com\n\nBody")
            email = ParsedEmail("Hello", "sender@example.com", "", "", "Body", "", source_path=source_path)
            settings = AppSettings(smtp_host="smtp.example.com", smtp_sender="forwarder@example.com")

            recipients = ForwardService(FakeSmtp).forward_email(
                email,
                settings,
                " one@example.com, two@example.com, ONE@example.com, ",
            )

            self.assertEqual(recipients, "one@example.com, two@example.com")
            self.assertEqual(FakeSmtp.sent_messages[0]["To"], recipients)


if __name__ == "__main__":
    unittest.main()
