# -*- mode: python ; coding: utf-8 -*-
"""Freeze Relinkbox for Windows.

Set RELINKBOX_ONEFILE=1 for a single exe. Leave it unset for the folder build
that gets zipped. build_release.ps1 runs both.
"""

import os
import re

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

onefile = os.environ.get("RELINKBOX_ONEFILE") == "1"

_version_text = open("relinkbox/__init__.py", encoding="utf-8").read()
_version = re.search(r'__version__\s*=\s*"([^"]+)"', _version_text).group(1)
_parts = [int(part) if part.isdigit() else 0 for part in _version.split(".")]
_parts = tuple((_parts + [0, 0, 0, 0])[:4])

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_parts, prodvers=_parts),
    kids=[
        StringFileInfo([
            StringTable(
                "040904B0",
                [
                    StringStruct("CompanyName", "TALE5"),
                    StringStruct("FileDescription", "Relink Rekordbox library tracks to files on disk"),
                    StringStruct("FileVersion", _version),
                    StringStruct("InternalName", "Relinkbox"),
                    StringStruct("LegalCopyright", "Copyright (C) 2026 TALE5. GPL-3.0-or-later."),
                    StringStruct("OriginalFilename", "Relinkbox.exe"),
                    StringStruct("ProductName", "Relinkbox"),
                    StringStruct("ProductVersion", _version),
                ],
            )
        ]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

hiddenimports = [
    "sqlcipher3",
    "sqlcipher3.dbapi2",
    "sqlalchemy.dialects.sqlite.pysqlcipher",
    "PySide6.QtMultimedia",
]

# The app only uses Qt Widgets. Skip the large Qt modules PySide6 ships with.
excludes = [
    "PySide6.QtWebEngine",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtTest",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtTextToSpeech",
    "PySide6.QtVirtualKeyboard",
    "PySide6.QtHttpServer",
    "PySide6.QtSpatialAudio",
    "tkinter",
    "pytest",
    "hypothesis",
]

a = Analysis(
    ["relinkbox/__main__.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("fonts", "fonts"),
        ("OFL.txt", "."),
        ("relinkbox_brand_assets", "relinkbox_brand_assets"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe_kwargs = dict(
    name="Relinkbox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="relinkbox_brand_assets/app_icon/relinkbox.ico",
    version=version_info,
)

if onefile:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **exe_kwargs)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **exe_kwargs)
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="Relinkbox",
    )
