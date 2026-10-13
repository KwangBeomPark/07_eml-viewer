"""Keep displayed attachment indexes aligned with the bytes saved."""

from email.message import EmailMessage
from pathlib import Path
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eml_viewer.models.attachment_data import AttachmentInfo
from eml_viewer.services.attachment_service import AttachmentService
from eml_viewer.services.eml_parser import EmlParser, EmlParseError, ExtractedAttachment
from eml_viewer.services.file_operation_service import FileOperationService


def test_named_inline_text_does_not_shift_saved_attachment_index(tmp_path):
    message = EmailMessage()
    message.set_content("Named body text must not become attachment zero.")
    message["Content-Disposition"] = 'inline; filename="body.txt"'
    message.add_attachment(b"correct attachment", maintype="application",
                           subtype="octet-stream", filename="actual.bin")
    path = tmp_path / "named-body.eml"
    path.write_bytes(message.as_bytes())
    parser = EmlParser()
    displayed = parser.parse_file(path).attachments
    assert [item.filename for item in displayed] == ["actual.bin"]
    extracted = parser.extract_attachment(path, displayed[0].index)
    assert extracted.info.filename == "actual.bin"
    assert extracted.payload == b"correct attachment"
    bulk = list(parser.iter_extracted_attachments(path, [0]))
    assert bulk[0] == extracted


def attachment_email(tmp_path):
    message = EmailMessage()
    message.set_content("Plain body")
    message.add_alternative('<html><img src="cid:picture"></html>', subtype="html")
    message.get_payload()[1].add_related(
        b"inline image", maintype="image", subtype="png", cid="<picture>", filename="picture.png"
    )
    for name, payload in [("보고서.bin", b"first"), ("보고서.bin", b"second"), ("empty.bin", b"")]:
        message.add_attachment(payload, maintype="application", subtype="octet-stream", filename=name)
    nested = EmailMessage()
    nested.set_content("Nested body")
    nested.add_attachment(b"nested bytes", maintype="text", subtype="plain", filename="nested.txt")
    message.add_attachment(nested, filename="forwarded.eml")
    path = tmp_path / "attachments.eml"
    path.write_bytes(message.as_bytes())
    return path


def test_bulk_bytes_names_cid_zero_length_and_nested_parts_match_single(tmp_path):
    path = attachment_email(tmp_path)
    parser = EmlParser()
    displayed = parser.parse_file(path).attachments
    assert len(displayed) == 4  # CID excluded; existing message/rfc822 traversal preserved.
    expected = [parser.extract_attachment(path, item.index) for item in displayed]
    with patch.object(parser, "_load_message", wraps=parser._load_message) as load:
        actual = list(parser.iter_extracted_attachments(path, [item.index for item in displayed]))
    assert load.call_count == 1
    assert actual == expected
    assert actual[2].payload == b""
    assert actual[3].payload == b"nested bytes"


def test_only_requested_payloads_decoded_once_in_requested_order(tmp_path):
    path = attachment_email(tmp_path)
    parser = EmlParser()
    loaded = parser._load_message(path)
    targets = [part for part in parser._iter_leaf_parts(loaded)
               if part.get_content_disposition() == "attachment" and not part.is_multipart()]
    for part in targets:
        part.get_payload = Mock(wraps=part.get_payload)
    with patch.object(parser, "_load_message", return_value=loaded):
        result = list(parser.iter_extracted_attachments(path, [2, 0, 2]))
    assert [item.payload for item in result] == [b"", b"first", b""]
    # CID image and both unselected attachments remain undecoded.
    assert [part.get_payload.call_count for part in targets] == [0, 1, 0, 1, 0]
    assert [item.info.index for item in result] == [2, 0, 2]


def test_bulk_save_deduplicates_names_and_applies_motw(tmp_path):
    path = attachment_email(tmp_path)
    parser = EmlParser()
    attachments = parser.parse_file(path).attachments
    operations = FileOperationService()
    with patch.object(operations, "apply_mark_of_the_web", return_value=True) as motw:
        with patch.object(parser, "_load_message", wraps=parser._load_message) as load:
            saved = AttachmentService(parser, operations).save_attachments(
                path, attachments, tmp_path / "saved"
            )
    assert load.call_count == 1
    assert [item.path.name for item in saved] == ["보고서.bin", "보고서 (2).bin", "empty.bin", "nested.txt"]
    assert [item.path.read_bytes() for item in saved] == [b"first", b"second", b"", b"nested bytes"]
    assert [call.args[0] for call in motw.call_args_list] == [item.path for item in saved]


def test_empty_selection_does_not_read_source(tmp_path):
    parser = EmlParser()
    with patch.object(parser, "_load_message", side_effect=AssertionError("unexpected read")):
        assert AttachmentService(parser).save_attachments(tmp_path / "missing.eml", [], tmp_path) == []


def test_conflict_preserves_prior_save_existing_file_and_unwritten_later_file(tmp_path):
    path = attachment_email(tmp_path)
    parser = EmlParser()
    selected = parser.parse_file(path).attachments
    destination = tmp_path / "saved"
    destination.mkdir()
    collision = destination / "보고서 (2).bin"
    collision.write_bytes(b"keep old")
    service = AttachmentService(parser)
    with pytest.raises(FileExistsError):
        service.save_attachments(path, selected, destination)
    assert (destination / "보고서.bin").read_bytes() == b"first"
    assert collision.read_bytes() == b"keep old"
    assert not (destination / "empty.bin").exists()
    service.save_attachments(path, selected, destination, overwrite=True)
    assert collision.read_bytes() == b"second"


def test_invalid_index_fails_at_request_position_after_prior_write(tmp_path):
    path = attachment_email(tmp_path)
    parser = EmlParser()
    selected = parser.parse_file(path).attachments
    invalid = AttachmentInfo(index=99, filename="invalid.bin", content_type="application/octet-stream", size=0)
    destination = tmp_path / "saved"
    with pytest.raises(EmlParseError):
        AttachmentService(parser).save_attachments(path, [selected[0], invalid, selected[1]], destination)
    assert (destination / "보고서.bin").read_bytes() == b"first"
    assert not (destination / "invalid.bin").exists()
    assert not (destination / "보고서 (2).bin").exists()


def test_msg_bulk_keeps_existing_per_attachment_extraction(tmp_path):
    parser = EmlParser()
    items = [AttachmentInfo(index=i, filename=f"{i}.bin", content_type="application/octet-stream", size=1)
             for i in range(2)]
    with patch.object(parser, "extract_attachment", side_effect=[
        ExtractedAttachment(item, bytes([item.index])) for item in items
    ]) as extract:
        result = AttachmentService(parser).save_attachments(tmp_path / "email.MSG", items, tmp_path / "saved")
    assert [call.args[1] for call in extract.call_args_list] == [0, 1]
    assert [item.path.read_bytes() for item in result] == [b"\x00", b"\x01"]


def test_single_attachment_loads_source_message_once(tmp_path):
    """G3 draft: a single extraction still loads its source exactly once."""
    path = attachment_email(tmp_path)
    parser = EmlParser()
    with patch.object(parser, "_load_message", wraps=parser._load_message) as load:
        extracted = parser.extract_attachment(path, 0)
    load.assert_called_once_with(path)
    assert extracted.payload == b"first"


@pytest.mark.parametrize("index", [-1, 999])
def test_single_attachment_invalid_index_preserves_error(tmp_path, index):
    path = attachment_email(tmp_path)
    with pytest.raises(EmlParseError):
        EmlParser().extract_attachment(path, index)


def test_single_msg_delegates_without_loading_eml(tmp_path):
    path = tmp_path / "sample.MSG"
    parser = EmlParser()
    expected = object()
    with patch.object(parser, "_extract_msg_attachment", return_value=expected) as msg:
        with patch.object(parser, "_load_message") as load:
            assert parser.extract_attachment(path, 0) is expected
    msg.assert_called_once_with(path, 0)
    load.assert_not_called()


@pytest.mark.parametrize("index,expected", [(0, b"first"), (1, b"second"), (2, b""), (3, b"nested bytes")])
def test_single_attachment_decodes_only_target_once(tmp_path, index, expected):
    """Correct G3's spy setup without decoding payloads during classification."""
    path = attachment_email(tmp_path)
    parser = EmlParser()
    loaded = parser._load_message(path)
    candidates = [part for part in parser._iter_leaf_parts(loaded)
                  if part.get_content_disposition() == "attachment" and not part.is_multipart()]
    assert len(candidates) == 5  # CID image, three outer attachments, nested attachment.
    for part in candidates:
        part.get_payload = Mock(wraps=part.get_payload)
    with patch.object(parser, "_load_message", return_value=loaded) as load:
        extracted = parser.extract_attachment(path, index)
    load.assert_called_once_with(path)
    assert extracted.payload == expected
    assert extracted.info.size == len(expected)
    assert [part.get_payload.call_count for part in candidates] == [
        int(position == index + 1) for position in range(5)
    ]
