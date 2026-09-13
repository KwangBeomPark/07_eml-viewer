from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eml_viewer.services.eml_parser import EmlParser


class FakeMsgProperties:
    def __init__(self, content_id: str = "", hidden: bool = False) -> None:
        self._content_id = content_id
        self._hidden = hidden

    def str_prop_value(self, _property_id) -> str:
        return self._content_id

    def int_prop_value(self, _property_id) -> int:
        return int(self._hidden)


class FakeMsgAttachment:
    def __init__(
        self,
        filename: str,
        payload: bytes,
        mime_type: str = "application/octet-stream",
        content_id: str = "",
        hidden: bool = False,
    ) -> None:
        self.file_name = filename
        self.file_bytes = payload
        self.mime_type = mime_type
        self.properties = FakeMsgProperties(content_id, hidden)


class FakeMsg:
    subject = "MSG subject"
    sender = "sender@example.com"
    message_headers = {"To": "receiver@example.com", "Cc": "copy@example.com"}
    sent_date = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    body = "Plain MSG body"
    html_body = '<html><body><p>HTML MSG body</p><img src="cid:image001@example"></body></html>'
    recipients = ()
    attachments = (
        FakeMsgAttachment(
            "image001.png",
            b"png",
            "image/png",
            content_id="image001@example",
            hidden=True,
        ),
        FakeMsgAttachment("report.txt", b"hello", "text/plain"),
    )


class EmlParserTest(unittest.TestCase):
    def test_parse_msg_email(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "message.msg"
            path.write_bytes(b"fake msg")
            original_load = self._patch_oxmsg_load(FakeMsg())

            try:
                parsed = EmlParser().parse_file(path)
            finally:
                self._restore_oxmsg_load(original_load)

            self.assertEqual(parsed.subject, "MSG subject")
            self.assertEqual(parsed.sender, "sender@example.com")
            self.assertEqual(parsed.recipients, "receiver@example.com")
            self.assertEqual(parsed.cc, "copy@example.com")
            self.assertEqual(parsed.date, "2026-06-06 12:00:00 +0000")
            self.assertEqual(parsed.plain_body, "Plain MSG body")
            self.assertIn("HTML MSG body", parsed.html_body)
            self.assertEqual(len(parsed.inline_resources), 1)
            self.assertEqual(parsed.inline_resources[0].content_id, "image001@example")
            self.assertEqual(len(parsed.attachments), 1)
            self.assertEqual(parsed.attachments[0].filename, "report.txt")
            self.assertEqual(parsed.attachments[0].size, 5)

    def test_extract_msg_attachment_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "message.msg"
            path.write_bytes(b"fake msg")
            original_load = self._patch_oxmsg_load(FakeMsg())

            try:
                extracted = EmlParser().extract_attachment(path, 0)
            finally:
                self._restore_oxmsg_load(original_load)

            self.assertEqual(extracted.info.filename, "report.txt")
            self.assertEqual(extracted.payload, b"hello")

    def test_parse_plain_text_email(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "plain.eml"
            message = EmailMessage()
            message["Subject"] = "테스트 제목"
            message["From"] = "sender@example.com"
            message["To"] = "receiver@example.com"
            message["Date"] = "Sat, 06 Jun 2026 12:00:00 +0200"
            message.set_content("Plain 본문입니다.", charset="utf-8")
            path.write_bytes(message.as_bytes())

            parsed = EmlParser().parse_file(path)

            self.assertEqual(parsed.subject, "테스트 제목")
            self.assertEqual(parsed.sender, "sender@example.com")
            self.assertEqual(parsed.recipients, "receiver@example.com")
            self.assertIn("Plain 본문입니다.", parsed.plain_body)
            self.assertEqual(parsed.html_body, "")

    def test_parse_cc_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cc.eml"
            path.write_bytes(
                (
                    "Subject: Cc test\n"
                    "From: sender@example.com\n"
                    "To: receiver@example.com\n"
                    "Cc: copy@example.com\n"
                    "Content-Type: text/plain; charset=\"utf-8\"\n"
                    "\n"
                    "Body\n"
                ).encode("utf-8")
            )

            parsed = EmlParser().parse_file(path)

            self.assertEqual(parsed.recipients, "receiver@example.com")
            self.assertEqual(parsed.cc, "copy@example.com")

    def test_parse_html_email(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "html.eml"
            message = EmailMessage()
            message["Subject"] = "HTML 메일"
            message["From"] = "sender@example.com"
            message["To"] = "receiver@example.com"
            message.set_content("대체 텍스트", charset="utf-8")
            message.add_alternative("<html><body><b>HTML 본문</b></body></html>", subtype="html")
            path.write_bytes(message.as_bytes())

            parsed = EmlParser().parse_file(path)

            self.assertIn("대체 텍스트", parsed.plain_body)
            self.assertIn("HTML 본문", parsed.html_body)

    def test_html_only_email_generates_plain_text_from_nested_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "html_only_table.eml"
            message = EmailMessage()
            message["Subject"] = "HTML only"
            message["From"] = "sender@example.com"
            message["To"] = "receiver@example.com"
            message.set_content(
                """
                <html><body>
                <table><tr><td>Outer text<table><tr><td>Inner text</td></tr></table></td></tr></table>
                <img src="cid:image001@example" alt="chart">
                </body></html>
                """,
                subtype="html",
                charset="utf-8",
            )
            path.write_bytes(message.as_bytes())

            parsed = EmlParser().parse_file(path)

            self.assertTrue(parsed.plain_body_generated)
            self.assertIn("Outer text", parsed.plain_body)
            self.assertIn("Inner text", parsed.plain_body)
            self.assertIn("[Image: chart]", parsed.plain_body)

    def test_parse_attachment_info_and_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "attachment.eml"
            message = EmailMessage()
            message["Subject"] = "첨부 메일"
            message["From"] = "sender@example.com"
            message["To"] = "receiver@example.com"
            message.set_content("첨부가 있습니다.", charset="utf-8")
            message.add_attachment(b"hello", maintype="text", subtype="plain", filename="note.txt")
            path.write_bytes(message.as_bytes())

            parser = EmlParser()
            parsed = parser.parse_file(path)
            extracted = parser.extract_attachment(path, 0)

            self.assertEqual(len(parsed.attachments), 1)
            self.assertEqual(parsed.attachments[0].filename, "note.txt")
            self.assertEqual(parsed.attachments[0].content_type, "text/plain")
            self.assertEqual(parsed.attachments[0].size, 5)
            self.assertEqual(extracted.payload, b"hello")

    def test_missing_file_raises_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            EmlParser().parse_file("missing-file.eml")

    def test_inline_image_is_not_shown_as_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "outlook_like.eml"
            message = EmailMessage()
            message["Subject"] = "Outlook HTML"
            message["From"] = "sender@example.com"
            message["To"] = "receiver@example.com"
            message.set_content("plain body", charset="utf-8")
            message.add_alternative(
                '<html><body><p>HTML body</p><img src="cid:image001@example"></body></html>',
                subtype="html",
            )
            html_part = message.get_payload()[1]
            html_part.add_related(
                b"fake-png",
                maintype="image",
                subtype="png",
                cid="<image001@example>",
                disposition="inline",
                filename="image001.png",
            )
            message.add_attachment(
                b"real attachment",
                maintype="application",
                subtype="octet-stream",
                filename="report.txt",
            )
            path.write_bytes(message.as_bytes())

            parsed = EmlParser().parse_file(path)

            self.assertEqual(len(parsed.inline_resources), 1)
            self.assertEqual(parsed.inline_resources[0].content_id, "image001@example")
            self.assertEqual(len(parsed.attachments), 1)
            self.assertEqual(parsed.attachments[0].filename, "report.txt")

    def test_referenced_attachment_image_is_treated_as_inline_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "referenced_attachment_image.eml"
            message = EmailMessage()
            message["Subject"] = "Referenced image"
            message["From"] = "sender@example.com"
            message["To"] = "receiver@example.com"
            message.set_content("plain", charset="utf-8")
            message.add_alternative(
                '<html><body><table><tr><td><img src="cid:image001%40example"></td></tr></table></body></html>',
                subtype="html",
            )
            html_part = message.get_payload()[1]
            html_part.add_related(
                b"fake-png",
                maintype="image",
                subtype="png",
                cid="<image001@example>",
                disposition="attachment",
                filename="image001.png",
            )
            path.write_bytes(message.as_bytes())

            parsed = EmlParser().parse_file(path)

            self.assertEqual(len(parsed.inline_resources), 1)
            self.assertEqual(parsed.inline_resources[0].content_id, "image001@example")
            self.assertEqual(parsed.attachments, [])

    def test_content_location_image_is_treated_as_inline_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "content_location_image.eml"
            message = EmailMessage()
            message["Subject"] = "Content location"
            message["From"] = "sender@example.com"
            message["To"] = "receiver@example.com"
            message.set_content("plain", charset="utf-8")
            message.add_alternative(
                '<html><body><table><tr><td><img src="images/logo.png"></td></tr></table></body></html>',
                subtype="html",
            )
            html_part = message.get_payload()[1]
            html_part.add_related(
                b"fake-png",
                maintype="image",
                subtype="png",
                filename="logo.png",
                disposition="attachment",
            )
            image_part = html_part.get_payload()[1]
            image_part["Content-Location"] = "images/logo.png"
            path.write_bytes(message.as_bytes())

            parsed = EmlParser().parse_file(path)

            self.assertEqual(len(parsed.inline_resources), 1)
            self.assertEqual(parsed.inline_resources[0].content_location, "images/logo.png")
            self.assertEqual(parsed.attachments, [])

    def test_srcset_image_is_treated_as_inline_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "srcset_image.eml"
            message = EmailMessage()
            message["Subject"] = "Srcset image"
            message["From"] = "sender@example.com"
            message["To"] = "receiver@example.com"
            message.set_content("plain", charset="utf-8")
            message.add_alternative(
                '<html><body><img srcset="cid:image001@example 1x, images/logo.png 2x"></body></html>',
                subtype="html",
            )
            html_part = message.get_payload()[1]
            html_part.add_related(
                b"fake-png",
                maintype="image",
                subtype="png",
                cid="<image001@example>",
                disposition="attachment",
                filename="image001.png",
            )
            path.write_bytes(message.as_bytes())

            parsed = EmlParser().parse_file(path)

            self.assertEqual(len(parsed.inline_resources), 1)
            self.assertEqual(parsed.inline_resources[0].content_id, "image001@example")
            self.assertEqual(parsed.attachments, [])

    def test_parse_korean_subject_and_attachment_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "korean.eml"
            message = EmailMessage()
            message["Subject"] = "한글 제목"
            message["From"] = "sender@example.com"
            message["To"] = "receiver@example.com"
            message.set_content("본문입니다.", charset="utf-8")
            message.add_attachment(
                "첨부 내용".encode("utf-8"),
                maintype="text",
                subtype="plain",
                filename="한글첨부.txt",
            )
            path.write_bytes(message.as_bytes())

            parsed = EmlParser().parse_file(path)

            self.assertEqual(parsed.subject, "한글 제목")
            self.assertEqual(parsed.attachments[0].filename, "한글첨부.txt")

    def test_choose_longest_non_empty_body_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "multiple_plain.eml"
            path.write_bytes(
                (
                    "MIME-Version: 1.0\n"
                    "Subject: Multiple bodies\n"
                    "From: sender@example.com\n"
                    "To: receiver@example.com\n"
                    "Content-Type: multipart/mixed; boundary=\"b\"\n"
                    "\n"
                    "--b\n"
                    "Content-Type: text/plain; charset=\"utf-8\"\n"
                    "\n"
                    "short\n"
                    "--b\n"
                    "Content-Type: text/plain; charset=\"utf-8\"\n"
                    "\n"
                    "this is the longer real body\n"
                    "--b--\n"
                ).encode("utf-8")
            )

            parsed = EmlParser().parse_file(path)

            self.assertEqual(parsed.plain_body.strip(), "this is the longer real body")

    def test_unknown_charset_fallback_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "invalid_charset.eml"
            path.write_bytes(
                (
                    "MIME-Version: 1.0\n"
                    "Subject: Unknown Charset\n"
                    "From: sender@example.com\n"
                    "To: receiver@example.com\n"
                    "Content-Type: text/plain; charset=\"x-nonexistent-charset-123\"\n"
                    "\n"
                    "Fallback payload text: \ud55c\uae00 \ubcf8\ubb38\n"
                ).encode("utf-8")
            )

            parsed = EmlParser().parse_file(path)
            self.assertIn("Fallback payload text", parsed.plain_body)
            self.assertIn("Subject: Unknown Charset", parsed.raw_headers)

    def test_safe_decode_direct(self) -> None:
        from eml_viewer.services.eml_parser import _safe_decode

        # 정상 utf-8
        self.assertEqual(_safe_decode("테스트".encode("utf-8"), "utf-8"), "테스트")
        # 비정상 charset 이름이지만 utf-8 바이트인 경우
        self.assertEqual(_safe_decode("테스트".encode("utf-8"), "invalid_codec_xyz"), "테스트")
        # cp949 인코딩 바이트이고 charset이 비정상인 경우
        self.assertEqual(_safe_decode("한글".encode("cp949"), "invalid_codec_xyz"), "한글")

    def _patch_oxmsg_load(self, message: FakeMsg):
        from oxmsg import Message as OxMsgMessage

        original_load = OxMsgMessage.__dict__["load"]
        OxMsgMessage.load = staticmethod(lambda _path: message)
        return original_load

    def _restore_oxmsg_load(self, original_load) -> None:
        from oxmsg import Message as OxMsgMessage

        OxMsgMessage.load = original_load


if __name__ == "__main__":
    unittest.main()
