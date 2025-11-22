# PyInstaller hook for the `vosk` package.
# Collects dynamic libraries, data files and submodules so Vosk works at runtime.
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
import os
import glob

hiddenimports = collect_submodules('vosk')

# collect_data_files will grab non-python files under the package (models aren't packaged,
# but the native library (.dll/.pyd) that vosk uses may be present under site-packages).
# If your Vosk install exposes large model files, do NOT include them here — models should
# remain external and selected by the user at runtime.

datas = collect_data_files('vosk')

# Attempt to collect any dynamic libs (PyInstaller >= 5.4 provides collect_dynamic_libs).
# Also attempt to locate common binary filenames inside the installed `vosk` package and
# explicitly add them so builds don't require the developer to guess the full path.
binaries = []
try:
    from PyInstaller.utils.hooks import collect_dynamic_libs
    binaries = collect_dynamic_libs('vosk') or []
except Exception:
    binaries = []

try:
    import vosk as _vosk_pkg
    pkg_dir = os.path.dirname(_vosk_pkg.__file__)
    # common extensions that may contain the native code
    patterns = ('*.dll', '*.pyd', '*.so', 'libvosk*.*', '*_vosk*.*')
    for pat in patterns:
        for p in glob.glob(os.path.join(pkg_dir, pat)):
            # add as (src, dest) tuple so PyInstaller copies to top-level of bundle
            entry = (p, '.')
            if entry not in binaries:
                binaries.append(entry)
except Exception:
    # best-effort only; if import fails at build time the normal hook behavior will remain
    pass
