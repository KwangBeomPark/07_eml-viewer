"""Regression tests for current-folder listing reuse."""

from pathlib import Path
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eml_viewer.services.folder_navigation import FolderNavigationService


def _touch(path: Path) -> Path:
    path.write_text("mail", encoding="utf-8")
    return path


def _advance_directory_mtime(folder: Path, next_mtime_ns: int) -> int:
    stat_result = folder.stat()
    next_mtime_ns = max(next_mtime_ns, stat_result.st_mtime_ns + 1_000_000_000)
    os.utime(folder, ns=(stat_result.st_atime_ns, next_mtime_ns))
    return next_mtime_ns + 1_000_000_000


def test_reuses_listing_without_rescanning_when_directory_stamp_is_unchanged(tmp_path):
    _touch(tmp_path / "B.eml")
    _touch(tmp_path / "a.MSG")
    service = FolderNavigationService()
    real_scandir = os.scandir

    with patch("eml_viewer.services.folder_navigation.os.scandir", wraps=real_scandir) as scan:
        first = service.files(tmp_path)
        second = service.files(tmp_path)
        assert first == second
        assert scan.call_count == 1


def test_missed_watcher_changes_are_detected_by_directory_stamp(tmp_path):
    first = _touch(tmp_path / "a.eml")
    service = FolderNavigationService()
    real_scandir = os.scandir

    with patch("eml_viewer.services.folder_navigation.os.scandir", wraps=real_scandir) as scan:
        assert [path.name for path in service.files(tmp_path)] == ["a.eml"]
        next_mtime_ns = tmp_path.stat().st_mtime_ns + 1_000_000_000

        _touch(tmp_path / "c.eml")
        next_mtime_ns = _advance_directory_mtime(tmp_path, next_mtime_ns)
        assert [path.name for path in service.files(tmp_path)] == ["a.eml", "c.eml"]

        (tmp_path / "c.eml").rename(tmp_path / "b.msg")
        next_mtime_ns = _advance_directory_mtime(tmp_path, next_mtime_ns)
        assert [path.name for path in service.files(tmp_path)] == ["a.eml", "b.msg"]

        first.unlink()
        _advance_directory_mtime(tmp_path, next_mtime_ns)
        assert service.files(tmp_path) == (tmp_path / "b.msg",)
        assert scan.call_count == 4


def test_directory_identity_change_rescans_even_when_mtime_matches(tmp_path):
    _touch(tmp_path / "one.eml")
    service = FolderNavigationService()
    real_scandir = os.scandir
    original_stamp = (1, 10, 1234)
    replacement_stamp = (1, 20, 1234)

    with patch.object(
        service,
        "_stat_folder",
        side_effect=[original_stamp, original_stamp,
                     replacement_stamp, replacement_stamp, replacement_stamp],
    ), patch("eml_viewer.services.folder_navigation.os.scandir", wraps=real_scandir) as scan:
        assert len(service.files(tmp_path)) == 1
        assert len(service.files(tmp_path)) == 1
        assert scan.call_count == 2


def test_refresh_forces_rescan_and_unmatched_invalidation_is_ignored(tmp_path):
    _touch(tmp_path / "one.eml")
    other = tmp_path / "other"
    other.mkdir()
    service = FolderNavigationService()
    real_scandir = os.scandir

    with patch("eml_viewer.services.folder_navigation.os.scandir", wraps=real_scandir) as scan:
        assert len(service.files(tmp_path)) == 1
        service.invalidate(other)
        assert len(service.files(tmp_path)) == 1
        assert scan.call_count == 1
        assert len(service.refresh(tmp_path)) == 1
        assert scan.call_count == 2


def test_switching_folders_scans_each_and_keeps_current_selection_findable(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    current = _touch(first / "z.eml")
    _touch(first / "A.msg")
    _touch(second / "only.eml")
    service = FolderNavigationService()

    listing = service.files(first)
    assert listing.index(current) == 1
    assert [path.name for path in service.files(second)] == ["only.eml"]
    assert [path.name for path in service.files(first)] == ["A.msg", "z.eml"]


def test_filters_extensions_and_directories(tmp_path):
    _touch(tmp_path / "mail.EML")
    _touch(tmp_path / "mail.msg")
    _touch(tmp_path / "notes.txt")
    (tmp_path / "folder.eml").mkdir()
    service = FolderNavigationService()
    assert [path.name for path in service.files(tmp_path)] == ["mail.EML", "mail.msg"]


def test_missing_folder_raises_and_drops_previous_listing(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    _touch(existing / "mail.eml")
    missing = tmp_path / "missing"
    service = FolderNavigationService()
    assert len(service.files(existing)) == 1

    with pytest.raises(OSError):
        service.files(missing)
    with pytest.raises(OSError):
        service.files(missing)

    (existing / "mail.eml").unlink()
    existing.rmdir()
    with pytest.raises(OSError):
        service.files(existing)
