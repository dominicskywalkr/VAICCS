# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

# Collect dynamic libs and submodules for vosk so native components are bundled
vosk_binaries = collect_dynamic_libs('vosk') or []
vosk_hidden = collect_submodules('vosk') or []

# Conditionally include additional DLLs depending on the Windows release.
# On Windows 7 include `api-ms-win-core-path-l1-1-0.dll` and the Python DLL.
# On Windows 8 / 8.1 include only the Python DLL. When building the
# executable the spec runs on the build host so we detect the host OS
# and search common locations for the DLLs to add them to the bundle.
import os
import sys

extra_binaries = []
if sys.platform == 'win32':
    # Python DLL name for Python 3.x -> e.g. python313.dll for 3.13
    py_dll_name = f"python{sys.version_info.major}{sys.version_info.minor}.dll"

    # Candidate locations to search for DLLs
    candidates = []
    # Directory containing the running python executable
    try:
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, py_dll_name))
    except Exception:
        pass

    # sys.base_prefix (installation root) and its possible DLL locations
    for prefix in (getattr(sys, 'base_prefix', None), getattr(sys, 'exec_prefix', None)):
        if prefix:
            candidates.append(os.path.join(prefix, py_dll_name))
            candidates.append(os.path.join(prefix, 'DLLs', py_dll_name))
            candidates.append(os.path.join(prefix, 'libs', py_dll_name))

    # System directories where the Python DLL might be located (32/64-bit)
    system_root = os.environ.get('SystemRoot') or r'C:\Windows'

    # Also add system32/python dll paths just in case
    candidates.append(os.path.join(system_root, 'System32', py_dll_name))
    candidates.append(os.path.join(system_root, 'SysWOW64', py_dll_name))

    # Add python DLL if found
    found_py = None
    for p in candidates:
        if p and os.path.isfile(p) and os.path.basename(p).lower() == py_dll_name.lower():
            found_py = p
            break
    if found_py:
        extra_binaries.append((found_py, '.'))

    # No Windows 7-specific DLLs are included — only the Python DLL is collected.

# Merge vosk binaries with any extra DLLs we found
all_binaries = (vosk_binaries or []) + extra_binaries

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=all_binaries,
    datas=[],
    hiddenimports=vosk_hidden,
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
    a.binaries,
    a.datas,
    [],
    name='VAICCS',
    icon='icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # Exclude the Vosk native DLL from UPX compression to avoid
    # runtime decompression failures ("decompression resulted in return code -1").
    # You can add other native DLL names here if needed.
    upx_exclude=['libvosk.dll'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
