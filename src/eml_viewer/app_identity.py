"""Dependency-free product identity and PL Suite registry integration for EML Viewer.

Maintains suite naming standards (App07_EmlViewer), install directory conventions,
UserSetting directory layout, and read-only fallback integration with 00_Registry.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Suite & Application Identity
PRODUCT_ID = "App07_EmlViewer"
DISPLAY_NAME = "EML Viewer"
APP_EXE = "App07_EmlViewer.exe"
LEGACY_EXE_NAMES = ("EmlViewer.exe",)
APP_EXE_NAMES = (APP_EXE, *LEGACY_EXE_NAMES)

INSTALL_DIR = "EML Viewer"
LEGACY_INSTALL_DIRS = ("EmlViewer", "App07_EmlViewer")

USER_SETTING_DIR = "UserSetting"
CONFIG_FILENAME = "settings.json"

INSTALLER_APP_ID = "{A9D9B7C3-04B8-4D2F-B28C-5B18C01C9CE1}"
WINDOWS_APP_ID = "emlviewer.desktop.v1"
INSTALLER_BASENAME = f"{PRODUCT_ID}_Setup"

# 00_Registry PL Enterprise Suite Standard Root
SUITE_REG_ROOT = r"Software\VB and VBA Program Settings\PL_Suite"


def version_from_tag(tag_name: str) -> str | None:
    """Accept numeric release versions without accepting paths or prefixes."""
    raw_tag = tag_name.strip()
    version = raw_tag[1:] if raw_tag[:1].lower() == "v" else raw_tag
    return version if re.fullmatch(r"\d+(?:\.\d+)*", version) else None


def user_data_dir() -> Path:
    """Resolve the canonical UserSetting directory following PL Suite storage conventions.

    1. Frozen executable inside its own folder uses <AppDir>/UserSetting (portable & install).
    2. Installed application uses %LOCALAPPDATA%/Programs/<INSTALL_DIR>/UserSetting.
    3. Fallback uses %USERPROFILE%/AppData/Local/Programs/<INSTALL_DIR>/UserSetting or current working dir.
    """
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable)
        if exe_path.name.lower() in [name.lower() for name in APP_EXE_NAMES]:
            return exe_path.parent / USER_SETTING_DIR

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    elif os.environ.get("USERPROFILE"):
        base = Path(os.environ["USERPROFILE"]) / "AppData" / "Local"
    else:
        base = Path.cwd()

    return base / "Programs" / INSTALL_DIR / USER_SETTING_DIR


def legacy_roaming_settings_path() -> Path:
    """Legacy settings path under %APPDATA%/EmlViewer/settings.json."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "EmlViewer" / CONFIG_FILENAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "EmlViewer" / CONFIG_FILENAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "EmlViewer" / CONFIG_FILENAME


def read_suite_registry_value(section: str, name: str, default: str = "") -> str:
    """Read a REG_SZ value from the PL Enterprise Suite registry (00_Registry standard)."""
    if sys.platform != "win32":
        return default

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{SUITE_REG_ROOT}\\{section}") as key:
            value, _ = winreg.QueryValueEx(key, name)
            raw = str(value).strip()
            return os.path.expandvars(raw) if raw else default
    except OSError:
        return default


def is_suite_integration_enabled(app_section: str = "EmlViewer") -> bool:
    """Check if Suite integration is enabled for this application per PL-REG-ARCH-2026."""
    if sys.platform != "win32":
        return False
    flag = read_suite_registry_value(app_section, "IntegrationEnabled", "False")
    return flag.lower() in {"true", "1", "yes", "on"}


def get_suite_common_fallback(name: str, default: str = "", app_section: str = "EmlViewer") -> str:
    """Get common fallback value from PL_Suite\\Common only when app integration is enabled."""
    if not is_suite_integration_enabled(app_section):
        return os.path.expandvars(default) if default else default
    return read_suite_registry_value("Common", name, default)

