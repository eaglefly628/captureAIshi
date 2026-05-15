# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for captureAIshi desktop app.

Usage:
    pip install pyinstaller pywebview flask numpy pillow mss
    pyinstaller desktop_app.spec

Output: dist/captureAIshi/captureAIshi.exe  (one-dir mode, faster startup)
    or: dist/captureAIshi.exe               (one-file mode, see below)
"""

import os
import sys

block_cipher = None

# Project root (where this .spec file lives)
ROOT = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    [os.path.join(ROOT, 'desktop_app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # Flask templates and static files
        (os.path.join(ROOT, 'web', 'templates'), os.path.join('web', 'templates')),
        (os.path.join(ROOT, 'web', 'static'), os.path.join('web', 'static')),
    ],
    hiddenimports=[
        'flask',
        'webview',
        'numpy',
        'PIL',
        'mss',
        # All internal modules that might be imported lazily
        'drivers.ue5_console',
        'drivers.unity_socket',
        'drivers.cheat_engine',
        'drivers.manual',
        'grabbers.renderdoc_grabber',
        'grabbers.screenshot_grabber',
        'ui_hiders.chain',
        'ui_hiders.console_hider',
        'ui_hiders.renderdoc_hider',
        'ui_hiders.noop_hider',
        'core.snake_path',
        'core.cone_rotation',
        'core.tangent_smoothing',
        'core.waypoint',
        'utils.coords',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',       # Not needed in desktop_app (uses webview)
        'matplotlib',
        'scipy',
        'pandas',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='captureAIshi',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # No console window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,   # macOS only
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # Add icon path here: icon='assets/icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='captureAIshi',
)
