"""Legacy migration publishes only a verified complete copy without overwrites."""

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eml_viewer.services import settings_service
from eml_viewer.services.settings_service import SettingsService


@pytest.fixture
def migration(tmp_path, monkeypatch):
    source = tmp_path / "Roaming" / "settings.json"
    source.parent.mkdir()
    source.write_bytes(b'{"language": "ko", "smtp_port": 25}')
    target = tmp_path / "UserSetting" / "settings.json"
    monkeypatch.setattr(settings_service, "legacy_roaming_settings_path", lambda: source)
    return source, target


def test_copy_failure_has_no_partial_target_and_retry_succeeds(migration, monkeypatch):
    source, target = migration
    original = source.read_bytes()
    copy = shutil.copyfile

    def fail(_source, staged):
        staged.write_bytes(b'{"partial":')
        raise OSError("injected copy failure")

    monkeypatch.setattr(settings_service.shutil, "copyfile", fail)
    with pytest.raises(OSError, match="migration failed"):
        SettingsService(target, auto_migrate=True)
    assert not target.exists()
    assert not list(target.parent.iterdir())
    assert source.read_bytes() == original
    monkeypatch.setattr(settings_service.shutil, "copyfile", copy)
    service = SettingsService(target, auto_migrate=True)
    assert target.read_bytes() == original
    assert service.load_settings().smtp_port == 25
    assert source.read_bytes() == original


def test_source_change_during_copy_blocks_publication(migration, monkeypatch):
    source, target = migration
    copy = shutil.copyfile
    changed = b'{"language": "en", "smtp_port": 587}'

    def change(_source, staged):
        copy(_source, staged)
        source.write_bytes(changed)

    monkeypatch.setattr(settings_service.shutil, "copyfile", change)
    with pytest.raises(OSError):
        SettingsService(target, auto_migrate=True)
    assert source.read_bytes() == changed
    assert not target.exists()
    assert not list(target.parent.iterdir())


def test_incomplete_copy_is_rejected_even_without_copy_exception(migration, monkeypatch):
    source, target = migration
    original = source.read_bytes()
    monkeypatch.setattr(settings_service.shutil, "copyfile", lambda _, staged: staged.write_bytes(b'{}'))
    with pytest.raises(OSError):
        SettingsService(target, auto_migrate=True)
    assert not target.exists()
    assert source.read_bytes() == original
    assert not list(target.parent.iterdir())


def test_flush_failure_keeps_only_the_legacy_source(migration, monkeypatch):
    source, target = migration
    original = source.read_bytes()

    def fail(_):
        raise OSError("injected flush failure")

    monkeypatch.setattr(settings_service.os, "fsync", fail)
    with pytest.raises(OSError):
        SettingsService(target, auto_migrate=True)
    assert not target.exists()
    assert source.read_bytes() == original
    assert not list(target.parent.iterdir())


def test_raced_destination_wins_without_being_removed(migration, monkeypatch):
    source, target = migration
    original = source.read_bytes()
    raced = b'{"language": "en", "smtp_port": 2525}'
    link = settings_service.os.link

    def race(staged, destination):
        destination.write_bytes(raced)
        return link(staged, destination)

    monkeypatch.setattr(settings_service.os, "link", race)
    service = SettingsService(target, auto_migrate=True)
    assert service.load_settings().smtp_port == 2525
    assert target.read_bytes() == raced
    assert source.read_bytes() == original
    assert list(target.parent.iterdir()) == [target]


def test_existing_destination_skips_migration(migration, monkeypatch):
    source, target = migration
    target.parent.mkdir()
    target.write_bytes(b'{"smtp_port": 2525}')
    monkeypatch.setattr(settings_service.shutil, "copyfile", lambda *_: pytest.fail("copied"))
    SettingsService(target, auto_migrate=True)
    assert target.read_bytes() == b'{"smtp_port": 2525}'
    assert source.exists()


@pytest.mark.parametrize("content", [b'{"partial":', b'[]', b'\xff'])
def test_invalid_legacy_settings_do_not_create_default_target(migration, content):
    source, target = migration
    source.write_bytes(content)
    with pytest.raises(OSError):
        SettingsService(target, auto_migrate=True)
    assert source.read_bytes() == content
    assert not target.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows no-replace fallback")
def test_hard_link_unsupported_filesystem_falls_back_to_replace(migration, monkeypatch):
    source, target = migration
    original = source.read_bytes()

    def fail_link(_staged, _destination):
        raise OSError(1, "Function not supported")

    monkeypatch.setattr(settings_service.os, "link", fail_link)
    service = SettingsService(target, auto_migrate=True)
    assert target.exists()
    assert target.read_bytes() == original
    assert service.load_settings().smtp_port == 25
    assert source.read_bytes() == original
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows no-replace fallback")
def test_windows_fallback_preserves_raced_destination(migration, monkeypatch):
    source, target = migration
    original = source.read_bytes()
    raced = b'{"smtp_port": 2525}'
    move = settings_service._move_windows_no_replace

    def unsupported(*_):
        raise OSError("Hard links unsupported")

    def race(staged, destination):
        destination.write_bytes(raced)
        move(staged, destination)

    monkeypatch.setattr(settings_service.os, "link", unsupported)
    monkeypatch.setattr(settings_service, "_move_windows_no_replace", race)
    service = SettingsService(target, auto_migrate=True)
    assert service.load_settings().smtp_port == 2525
    assert target.read_bytes() == raced
    assert source.read_bytes() == original
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows no-replace fallback")
def test_windows_fallback_permission_failure_keeps_original(migration, monkeypatch):
    source, target = migration
    original = source.read_bytes()

    def unsupported(*_):
        raise OSError("Hard links unsupported")

    def denied(*_):
        raise PermissionError("Injected access denied")

    monkeypatch.setattr(settings_service.os, "link", unsupported)
    monkeypatch.setattr(settings_service, "_move_windows_no_replace", denied)
    with pytest.raises(OSError, match="migration failed"):
        SettingsService(target, auto_migrate=True)
    assert not target.exists()
    assert source.read_bytes() == original
    assert not list(target.parent.iterdir())
