# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path(SPECPATH).resolve().parent
src_root = project_root / "src"
app_icon = project_root / "assets" / "app.ico"


a = Analysis(
    [str(src_root / "eml_viewer" / "__main__.py")],
    pathex=[str(src_root)],
    binaries=[],
    datas=[
        (str(app_icon), "assets"),
        (str(src_root / "eml_viewer" / "i18n" / "locales"), "eml_viewer/i18n/locales"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EmlViewer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(app_icon),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EmlViewer",
)
