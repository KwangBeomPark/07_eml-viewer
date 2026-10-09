from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SHORTCUT_NAME = "EML Viewer.lnk"
DEFAULT_ARGUMENTS = "--tray"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _CLSID_ShellLink = "{00021401-0000-0000-C000-000000000046}"
    _IID_IShellLinkW = "{000214F9-0000-0000-C000-000000000046}"
    _IID_IPersistFile = "{0000010b-0000-0000-C000-000000000046}"

    class _GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8),
        ]

        @classmethod
        def from_str(cls, guid_str: str) -> _GUID:
            guid = cls()
            ctypes.windll.ole32.CLSIDFromString(wintypes.LPCWSTR(guid_str), ctypes.byref(guid))
            return guid

    class _IShellLinkW_Vtbl(ctypes.Structure):
        _fields_ = [
            ("QueryInterface", ctypes.c_void_p),
            ("AddRef", ctypes.c_void_p),
            ("Release", ctypes.c_void_p),
            ("GetPath", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.LPWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)),
            ("GetIDList", ctypes.c_void_p),
            ("SetIDList", ctypes.c_void_p),
            ("GetDescription", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.LPWSTR, ctypes.c_int)),
            ("SetDescription", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.LPCWSTR)),
            ("GetWorkingDirectory", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.LPWSTR, ctypes.c_int)),
            ("SetWorkingDirectory", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.LPCWSTR)),
            ("GetArguments", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.LPWSTR, ctypes.c_int)),
            ("SetArguments", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.LPCWSTR)),
            ("GetHotkey", ctypes.c_void_p),
            ("SetHotkey", ctypes.c_void_p),
            ("GetShowCmd", ctypes.c_void_p),
            ("SetShowCmd", ctypes.c_void_p),
            ("GetIconLocation", ctypes.c_void_p),
            ("SetIconLocation", ctypes.c_void_p),
            ("SetRelativePath", ctypes.c_void_p),
            ("Resolve", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.HWND, wintypes.DWORD)),
            ("SetPath", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.LPCWSTR)),
        ]

    class _IPersistFile_Vtbl(ctypes.Structure):
        _fields_ = [
            ("QueryInterface", ctypes.c_void_p),
            ("AddRef", ctypes.c_void_p),
            ("Release", ctypes.c_void_p),
            ("GetClassID", ctypes.c_void_p),
            ("IsDirty", ctypes.c_void_p),
            ("Load", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.LPCWSTR, wintypes.DWORD)),
            ("Save", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.LPCWSTR, wintypes.BOOL)),
            ("SaveCompleted", ctypes.c_void_p),
            ("GetCurFile", ctypes.c_void_p),
        ]

    class _IUnknown_Vtbl(ctypes.Structure):
        _fields_ = [
            ("QueryInterface", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))),
            ("AddRef", ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)),
            ("Release", ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)),
        ]

    def _create_shortcut_win32_com(shortcut_path: str, target: str, args: str, work_dir: str, desc: str) -> bool:
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        try:
            clsid = _GUID.from_str(_CLSID_ShellLink)
            iid_link = _GUID.from_str(_IID_IShellLinkW)
            iid_persist = _GUID.from_str(_IID_IPersistFile)

            p_link = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(clsid),
                None,
                1,  # CLSCTX_INPROC_SERVER
                ctypes.byref(iid_link),
                ctypes.byref(p_link),
            )
            if hr != 0:
                return False

            link_vtbl = ctypes.cast(
                ctypes.cast(p_link, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(_IShellLinkW_Vtbl)
            ).contents

            link_vtbl.SetPath(p_link, target)
            if args:
                link_vtbl.SetArguments(p_link, args)
            if work_dir:
                link_vtbl.SetWorkingDirectory(p_link, work_dir)
            if desc:
                link_vtbl.SetDescription(p_link, desc)

            iunknown_vtbl = ctypes.cast(
                ctypes.cast(p_link, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(_IUnknown_Vtbl)
            ).contents

            p_persist = ctypes.c_void_p()
            hr = iunknown_vtbl.QueryInterface(p_link, ctypes.byref(iid_persist), ctypes.byref(p_persist))
            if hr != 0:
                iunknown_vtbl.Release(p_link)
                return False

            persist_vtbl = ctypes.cast(
                ctypes.cast(p_persist, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(_IPersistFile_Vtbl)
            ).contents

            save_hr = persist_vtbl.Save(p_persist, shortcut_path, True)

            persist_iunknown = ctypes.cast(
                ctypes.cast(p_persist, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(_IUnknown_Vtbl)
            ).contents
            persist_iunknown.Release(p_persist)
            iunknown_vtbl.Release(p_link)

            return save_hr == 0
        finally:
            ole32.CoUninitialize()

    def _read_shortcut_win32_com(shortcut_path: str) -> str | None:
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        try:
            clsid = _GUID.from_str(_CLSID_ShellLink)
            iid_link = _GUID.from_str(_IID_IShellLinkW)
            iid_persist = _GUID.from_str(_IID_IPersistFile)

            p_link = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(clsid),
                None,
                1,  # CLSCTX_INPROC_SERVER
                ctypes.byref(iid_link),
                ctypes.byref(p_link),
            )
            if hr != 0:
                return None

            iunknown_vtbl = ctypes.cast(
                ctypes.cast(p_link, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(_IUnknown_Vtbl)
            ).contents

            p_persist = ctypes.c_void_p()
            hr = iunknown_vtbl.QueryInterface(p_link, ctypes.byref(iid_persist), ctypes.byref(p_persist))
            if hr != 0:
                iunknown_vtbl.Release(p_link)
                return None

            persist_vtbl = ctypes.cast(
                ctypes.cast(p_persist, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(_IPersistFile_Vtbl)
            ).contents

            load_hr = persist_vtbl.Load(p_persist, shortcut_path, 0)
            if load_hr != 0:
                persist_iunknown = ctypes.cast(
                    ctypes.cast(p_persist, ctypes.POINTER(ctypes.c_void_p)).contents,
                    ctypes.POINTER(_IUnknown_Vtbl)
                ).contents
                persist_iunknown.Release(p_persist)
                iunknown_vtbl.Release(p_link)
                return None

            link_vtbl = ctypes.cast(
                ctypes.cast(p_link, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(_IShellLinkW_Vtbl)
            ).contents

            buf = ctypes.create_unicode_buffer(1024)
            get_hr = link_vtbl.GetPath(p_link, buf, 1024, None, 0)

            persist_iunknown = ctypes.cast(
                ctypes.cast(p_persist, ctypes.POINTER(ctypes.c_void_p)).contents,
                ctypes.POINTER(_IUnknown_Vtbl)
            ).contents
            persist_iunknown.Release(p_persist)
            iunknown_vtbl.Release(p_link)

            if get_hr == 0 and buf.value:
                return buf.value
            return None
        finally:
            ole32.CoUninitialize()


class StartupManager:
    """Windows 시작프로그램 바로가기(.lnk) 등록 및 삭제를 관리합니다."""

    def __init__(
        self,
        startup_dir: Path | None = None,
        shortcut_name: str = DEFAULT_SHORTCUT_NAME,
        target_path: Path | str | None = None,
        arguments: str = DEFAULT_ARGUMENTS,
    ) -> None:
        self._startup_dir = startup_dir
        self._shortcut_name = shortcut_name
        self._target_path = target_path
        self._arguments = arguments

    def get_startup_dir(self) -> Path:
        if self._startup_dir is not None:
            return self._startup_dir

        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"

        # Fallback if APPDATA is not defined (e.g. non-Windows test environment)
        return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"

    def get_shortcut_path(self) -> Path:
        return self.get_startup_dir() / self._shortcut_name

    def is_startup_enabled(self) -> bool:
        shortcut = self.get_shortcut_path()
        return shortcut.exists() and shortcut.is_file()

    def is_target_current(self) -> bool:
        """바로가기가 현재 실행 파일(또는 지정된 대상)을 올바르게 가리키고 있는지 확인합니다."""
        if not self.is_startup_enabled():
            return False
        expected_target, _, _ = self.get_resolved_target()
        actual_target = self.get_shortcut_target()
        if actual_target is None:
            return False
        try:
            return Path(actual_target).resolve() == Path(expected_target).resolve()
        except Exception:
            return actual_target.lower() == str(Path(expected_target).resolve()).lower()

    def get_resolved_target(self) -> tuple[str, str, str]:
        """(target_path, arguments, working_directory) 튜플을 반환합니다."""
        if self._target_path is not None:
            target = str(Path(self._target_path).resolve())
            working_dir = str(Path(target).parent)
            return target, self._arguments, working_dir

        is_frozen = getattr(sys, "frozen", False)
        if is_frozen:
            target = sys.executable
            working_dir = str(Path(target).parent)
            return target, self._arguments, working_dir

        # 개발 환경: pythonw.exe 또는 python.exe로 모듈 실행
        target = sys.executable
        working_dir = str(Path(__file__).resolve().parents[3])
        pythonw = Path(target).with_name("pythonw.exe")
        if pythonw.exists():
            target = str(pythonw)

        args = f"-m eml_viewer {self._arguments}".strip()
        return target, args, working_dir

    def enable_startup(self) -> bool:
        shortcut_path = self.get_shortcut_path()
        try:
            shortcut_path.parent.mkdir(parents=True, exist_ok=True)
            target, args, working_dir = self.get_resolved_target()

            if sys.platform != "win32":
                # Non-Windows 환경 (테스트 등): 마커 파일로 생성
                shortcut_path.write_text(f"TargetPath={target}\nArguments={args}\n", encoding="utf-8")
                logger.info("Startup mock shortcut created at %s", shortcut_path)
                return True

            # Windows: 1순위로 네이티브 COM (IShellLinkW) 사용 (0.001초 속도 및 완벽한 유니코드 경로 지원)
            try:
                if _create_shortcut_win32_com(
                    str(shortcut_path),
                    str(target),
                    str(args),
                    str(working_dir),
                    "EML Viewer Background Warm-Start Preload",
                ):
                    logger.info("Startup shortcut successfully created via native COM at %s", shortcut_path)
                    return True
            except Exception as com_exc:
                logger.debug("Native COM shortcut creation failed; falling back to PowerShell: %s", com_exc)

            # Fallback: PowerShell WScript.Shell
            def _ps_quote(s: str) -> str:
                return "'" + s.replace("'", "''") + "'"

            ps_cmd = (
                f"$ws = New-Object -ComObject WScript.Shell; "
                f"$s = $ws.CreateShortcut({_ps_quote(str(shortcut_path))}); "
                f"$s.TargetPath = {_ps_quote(str(target))}; "
                f"$s.Arguments = {_ps_quote(str(args))}; "
                f"$s.WorkingDirectory = {_ps_quote(str(working_dir))}; "
                f"$s.Description = 'EML Viewer Background Warm-Start Preload'; "
                f"$s.Save()"
            )

            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                creationflags=creation_flags,
                timeout=10,
            )

            if result.returncode != 0:
                logger.error("Failed to create startup shortcut: %s", result.stderr)
                return False

            logger.info("Startup shortcut successfully created at %s", shortcut_path)
            return True
        except Exception as exc:
            logger.error("Exception creating startup shortcut: %s", exc)
            return False

    def disable_startup(self) -> bool:
        shortcut_path = self.get_shortcut_path()
        try:
            if shortcut_path.exists():
                shortcut_path.unlink()
                logger.info("Startup shortcut removed from %s", shortcut_path)
            return True
        except Exception as exc:
            logger.error("Failed to remove startup shortcut: %s", exc)
            return False

    def set_startup_enabled(self, enabled: bool) -> bool:
        if enabled:
            return self.enable_startup()
        return self.disable_startup()

    def get_shortcut_target(self) -> str | None:
        """기존 바로가기 파일이 가리키는 대상 파일(TargetPath)의 정규화된 경로를 반환합니다."""
        shortcut_path = self.get_shortcut_path()
        if not shortcut_path.exists():
            return None

        if sys.platform != "win32":
            # Non-Windows 환경: 테스트용 마커 파일 파싱
            try:
                for line in shortcut_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("TargetPath="):
                        val = line.split("=", 1)[1].strip()
                        return str(Path(val).resolve())
            except Exception:
                pass
            return None

        # Windows: 1순위로 네이티브 COM (IShellLinkW) 사용
        try:
            target = _read_shortcut_win32_com(str(shortcut_path))
            if target:
                return str(Path(target).resolve())
        except Exception as com_exc:
            logger.debug("Native COM shortcut read failed; falling back to PowerShell: %s", com_exc)

        # Fallback: PowerShell WScript.Shell
        try:
            def _ps_quote(s: str) -> str:
                return "'" + s.replace("'", "''") + "'"

            ps_cmd = (
                f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
                f"$ws = New-Object -ComObject WScript.Shell; "
                f"$s = $ws.CreateShortcut({_ps_quote(str(shortcut_path))}); "
                f"[Console]::WriteLine($s.TargetPath)"
            )
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
                timeout=5,
            )
            if result.returncode == 0:
                raw_target = result.stdout.strip()
                if raw_target:
                    return str(Path(raw_target).resolve())
        except Exception as exc:
            logger.warning("Failed to resolve shortcut target: %s", exc)
        return None

    def cleanup_if_target_matches(self, expected_target: Path | str | None = None) -> bool:
        """바로가기가 지정된 대상(기본값: 현재 실행 파일)을 가리키는 경우에만 안전하게 삭제합니다."""
        shortcut_path = self.get_shortcut_path()
        if not shortcut_path.exists():
            return False

        if expected_target is None:
            expected_target, _, _ = self.get_resolved_target()

        expected_norm = str(Path(expected_target).resolve()).lower()
        actual_target = self.get_shortcut_target()
        if actual_target is None:
            return False

        if actual_target.lower() == expected_norm:
            try:
                shortcut_path.unlink()
                logger.info("Cleaned up matching startup shortcut: %s -> %s", shortcut_path, actual_target)
                return True
            except Exception as exc:
                logger.error("Failed to delete matching startup shortcut: %s", exc)
                return False

        logger.info(
            "Startup shortcut points to different target (%s != %s); preserving.",
            actual_target,
            expected_norm,
        )
        return False

    def backup_shortcut(self) -> bytes | None:
        """기존 바로가기 파일의 내용을 바이트 단위로 백업합니다. 파일이 없으면 None을 반환합니다."""
        shortcut = self.get_shortcut_path()
        if not shortcut.exists():
            return None
        try:
            return shortcut.read_bytes()
        except Exception as exc:
            logger.warning("Failed to backup shortcut bytes: %s", exc)
            raise OSError(f"Cannot backup existing shortcut at {shortcut}: {exc}") from exc

    def restore_shortcut(self, backup: bytes | None) -> bool:
        """이전에 백업된 바로가기 파일 내용을 원래대로 100% 복원합니다."""
        shortcut = self.get_shortcut_path()
        try:
            if backup is None:
                if shortcut.exists():
                    shortcut.unlink()
                return True
            else:
                shortcut.parent.mkdir(parents=True, exist_ok=True)
                shortcut.write_bytes(backup)
                return True
        except Exception as exc:
            logger.error("Failed to restore shortcut from backup: %s", exc)
            return False
