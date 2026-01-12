# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for `launcher.py`.

Ensures the `vosk` Python package and its native library are bundled
correctly using a dedicated hook (`hook-vosk.py`) and a runtime hook
(`hooks/rth_vosk_fix.py`).
"""
import os
from PyInstaller.utils.hooks import collect_submodules

pathex = [os.path.abspath('.')]

# Use the dedicated Vosk hook (hook-vosk.py) to collect the Python package,
# its extension module(s), and native libraries.
binaries = []
datas = []

a = Analysis(
    ['launcher.py'],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    # Vosk is imported lazily in `main.py` (inside a method), which PyInstaller
    # may not discover automatically. Include the package explicitly.
    hiddenimports=['vosk'] + collect_submodules('vosk'),
    hookspath=[os.path.abspath('.'), os.path.abspath('hooks')],
    runtime_hooks=[os.path.join('hooks', 'rth_vosk_fix.py')],
    excludes=[],
    # Vosk's `open_dll()` uses `os.path.dirname(__file__)` to locate
    # `libvosk.dyld`. Keeping pure-Python modules inside PYZ can yield a
    # non-filesystem `__file__` that breaks this lookup when launched via Finder.
    # `noarchive=True` materializes pure modules on disk inside the bundle.
    noarchive=True,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VAICCS',
    icon=None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='VAICCS',
)

app = BUNDLE(
    coll,
    name='VAICCS.app',
    icon=None,
    bundle_identifier='com.dominic.vaiccs',
    # No entitlements -> no app sandbox.
    entitlements_file=None,
)
