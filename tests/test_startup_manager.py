from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eml_viewer.services.startup_manager import StartupManager


def test_startup_manager_paths(tmp_path: Path):
    manager = StartupManager(startup_dir=tmp_path, shortcut_name="Test.lnk")
    assert manager.get_startup_dir() == tmp_path
    assert manager.get_shortcut_path() == tmp_path / "Test.lnk"
    assert not manager.is_startup_enabled()


def test_startup_manager_resolved_target_custom(tmp_path: Path):
    target = tmp_path / "App.exe"
    target.touch()
    manager = StartupManager(
        startup_dir=tmp_path,
        target_path=target,
        arguments="--tray",
    )
    t, args, wdir = manager.get_resolved_target()
    assert t == str(target.resolve())
    assert args == "--tray"
    assert wdir == str(tmp_path)


def test_startup_manager_enable_and_disable_mock(tmp_path: Path):
    manager = StartupManager(
        startup_dir=tmp_path,
        shortcut_name="TestApp.lnk",
        target_path=tmp_path / "TestApp.exe",
        arguments="--tray",
    )

    with patch("sys.platform", "linux"):
        # non-win32 fallback writes mock file
        assert manager.enable_startup()
        assert manager.is_startup_enabled()
        content = manager.get_shortcut_path().read_text(encoding="utf-8")
        assert "TargetPath=" in content
        assert "Arguments=--tray" in content

        # disable removes it
        assert manager.disable_startup()
        assert not manager.is_startup_enabled()


def test_startup_manager_set_startup_enabled(tmp_path: Path):
    manager = StartupManager(
        startup_dir=tmp_path,
        shortcut_name="Toggle.lnk",
        target_path=tmp_path / "Toggle.exe",
    )
    with patch("sys.platform", "linux"):
        assert manager.set_startup_enabled(True)
        assert manager.is_startup_enabled()

        assert manager.set_startup_enabled(False)
        assert not manager.is_startup_enabled()


def test_startup_manager_single_quote_path(tmp_path: Path):
    # O'Brien 처럼 작은따옴표가 포함된 특수 경로에서도 정상 생성/삭제되는지 검증
    special_dir = tmp_path / "O'Brien" / "Startup"
    target = tmp_path / "App's File.exe"
    target.touch()

    manager = StartupManager(
        startup_dir=special_dir,
        shortcut_name="EML Viewer.lnk",
        target_path=target,
        arguments="--tray",
    )

    # Windows에서 실제 PowerShell 호출 테스트
    assert manager.enable_startup()
    assert manager.is_startup_enabled()
    assert manager.disable_startup()
    assert not manager.is_startup_enabled()


def test_startup_manager_cleanup_if_target_matches(tmp_path: Path):
    target1 = tmp_path / "App1.exe"
    target1.touch()
    target2 = tmp_path / "App2.exe"
    target2.touch()

    manager1 = StartupManager(
        startup_dir=tmp_path,
        shortcut_name="EML Viewer.lnk",
        target_path=target1,
    )
    assert manager1.enable_startup()
    assert manager1.is_startup_enabled()

    # target2로 cleanup 시도 시 타깃이 불일치하므로 삭제되지 않아야 함
    assert not manager1.cleanup_if_target_matches(target2)
    assert manager1.is_startup_enabled()

    # target1으로 cleanup 시도 시 타깃이 일치하므로 삭제되어야 함
    assert manager1.cleanup_if_target_matches(target1)
    assert not manager1.is_startup_enabled()


def test_startup_manager_backup_and_restore_shortcut(tmp_path: Path):
    target1 = tmp_path / "Installed.exe"
    target1.touch()
    target2 = tmp_path / "Portable.exe"
    target2.touch()

    manager = StartupManager(
        startup_dir=tmp_path,
        shortcut_name="EML Viewer.lnk",
        target_path=target1,
    )
    # 1. 원래 다른 타깃(Installed.exe)으로 생성된 바로가기가 존재함
    assert manager.enable_startup()
    orig_target = manager.get_shortcut_target()
    assert orig_target is not None and "Installed.exe" in orig_target

    # 2. 백업 수행
    backup = manager.backup_shortcut()
    assert backup is not None

    # 3. 다른 사본(Portable.exe)으로 바로가기를 변경함
    manager2 = StartupManager(
        startup_dir=tmp_path,
        shortcut_name="EML Viewer.lnk",
        target_path=target2,
    )
    assert manager2.enable_startup()
    assert "Portable.exe" in manager2.get_shortcut_target()

    # 4. 롤백(복원) 수행 시 원래 Installed.exe 대상이 100% 바이트 단위로 복원되어야 함
    assert manager2.restore_shortcut(backup)
    restored_target = manager2.get_shortcut_target()
    assert restored_target == orig_target


def test_startup_manager_is_target_current(tmp_path: Path):
    target1 = tmp_path / "AppA" / "EmlViewer.exe"
    target2 = tmp_path / "AppB" / "EmlViewer.exe"
    target1.parent.mkdir(parents=True)
    target1.touch()
    target2.parent.mkdir(parents=True)
    target2.touch()

    manager1 = StartupManager(startup_dir=tmp_path, target_path=target1)
    manager2 = StartupManager(startup_dir=tmp_path, target_path=target2)

    assert not manager1.is_target_current()
    assert manager1.enable_startup()
    assert manager1.is_target_current()
    assert not manager2.is_target_current()


def test_startup_manager_unicode_path(tmp_path: Path):
    """유니코드(Łódź 등) 경로가 포함된 실행 파일에 대해서도 바로가기 생성 및 대상 조회가 일치하는지 검증합니다."""
    target = tmp_path / "Łódź" / "EmlViewer.exe"
    target.parent.mkdir(parents=True)
    target.touch()

    manager = StartupManager(startup_dir=tmp_path, target_path=target)
    assert manager.enable_startup()
    shortcut_target = manager.get_shortcut_target()
    assert shortcut_target is not None
    assert Path(shortcut_target).resolve() == target.resolve()
    assert manager.is_target_current()


def test_startup_manager_damaged_shortcut_not_current(tmp_path: Path):
    """내용이 손상되었거나 파싱할 수 없는 바로가기 파일이 존재할 때 is_target_current가 False를 반환하는지 검증합니다."""
    target = tmp_path / "App" / "EmlViewer.exe"
    target.parent.mkdir(parents=True)
    target.touch()

    manager = StartupManager(startup_dir=tmp_path, target_path=target)
    # 손상된 임의 바이트로 바로가기 생성
    manager.get_shortcut_path().write_bytes(b"not a valid shell link shortcut")

    assert manager.is_startup_enabled()
    assert manager.get_shortcut_target() is None
    assert not manager.is_target_current()
