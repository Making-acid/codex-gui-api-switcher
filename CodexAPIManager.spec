# -*- mode: python ; coding: utf-8 -*-
"""Codex API Manager — PyInstaller 打包配置（单文件 exe）。"""
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []

# pywebview 及其 Windows 平台依赖（pythonnet / clr_loader 原生库）
for pkg in ("pywebview", "clr_loader", "pythonnet"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += [
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
]

datas += [
    ("static", "static"),
    ("templates", "templates"),
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CodexAPIManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
