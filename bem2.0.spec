# -*- mode: python ; coding: utf-8 -*-
# Folder build of Backblaze Exclusion Manager 2: bem2.0.exe with its files next to it in _internal, nothing unpacked at start.
# build\ and dist\ are created in the folder PyInstaller is run from, so from the folder that holds them run:
#     bzvenv\Scripts\pyinstaller.exe --noconfirm backblaze-exclusion-manager\bem2.0.spec
# The result is dist\bem2.0\bem2.0.exe. The whole dist\bem2.0 folder is the portable app.
import os

HERE = SPECPATH
NAME = "bem2.0"
ICON = os.path.join(HERE, "icon.ico")

a = Analysis(
    [os.path.join(HERE, "app.py")],
    pathex=[HERE],
    binaries=[],
    # app.py looks for icon.ico next to itself, which in the built app is the _internal folder
    datas=[(ICON, ".")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # the 1.1 app in gui.py uses these, version 2 does not
    excludes=["tkinter", "customtkinter", "darkdetect"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    icon=ICON,
    console=False,
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=NAME,
)
