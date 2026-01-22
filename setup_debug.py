"""py2app build script for VAICCS Debug.

This builds the debug variant app (launcher_debug.py).

Build:
  python3 -m pip install -U py2app
  python3 setup_debug.py py2app

Fast iteration:
  python3 setup_debug.py py2app -A
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import subprocess
import tempfile

from setuptools import setup


PROJECT_ROOT = Path(__file__).resolve().parent

# Avoid failures copying macOS extended attributes (xattrs) from root-owned
# framework files into the bundle (can error with EPERM on some systems).
os.environ.setdefault("COPYFILE_DISABLE", "1")


def _detect_or_build_iconfile() -> str | None:
    """Return a usable .icns path for py2app, best-effort.

    py2app expects an .icns for the bundle icon. We keep `icon.ico` around
    because parts of the GUI code also use it at runtime (e.g. Tk icons).
    """

    # For the macOS .app icon, prefer building an .icns from the Icon Composer
    # exports folder (best-effort). We intentionally do not use `icon.icns`
    # as the bundle icon.
    if sys.platform == "darwin":
        default_png = (
            PROJECT_ROOT
            / "VAICCS Exports"
            / "VAICCS-iOS-Default-1024x1024@1x.png"
        )
        if default_png.exists():
            icns = PROJECT_ROOT / "VAICCS.icns"
            try:
                with tempfile.TemporaryDirectory() as td:
                    iconset = Path(td) / "VAICCS.iconset"
                    iconset.mkdir(parents=True, exist_ok=True)

                    def _mk(size: int, name: str):
                        out = iconset / name
                        subprocess.run(
                            [
                                "sips",
                                "-z",
                                str(size),
                                str(size),
                                str(default_png),
                                "--out",
                                str(out),
                            ],
                            check=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )

                    # Minimal iconset sizes for iconutil.
                    _mk(16, "icon_16x16.png")
                    _mk(32, "icon_16x16@2x.png")
                    _mk(32, "icon_32x32.png")
                    _mk(64, "icon_32x32@2x.png")
                    _mk(128, "icon_128x128.png")
                    _mk(256, "icon_128x128@2x.png")
                    _mk(256, "icon_256x256.png")
                    _mk(512, "icon_256x256@2x.png")
                    _mk(512, "icon_512x512.png")
                    _mk(1024, "icon_512x512@2x.png")
                    _mk(1024, "icon_1024x1024.png")

                    subprocess.run(
                        ["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )

                if icns.exists():
                    return str(icns.resolve())
            except Exception:
                pass

    icns = PROJECT_ROOT / "VAICCS.icns"

    ico = PROJECT_ROOT / "icon.ico"
    if not ico.exists():
        return None

    try:
        from PIL import Image  # type: ignore

        im = Image.open(str(ico))
        im.save(str(icns), format="ICNS")
        if icns.exists():
            return str(icns.resolve())
    except Exception:
        return None

    return None


def _read_version() -> str:
    try:
        import main as mainmod

        v = getattr(mainmod, "__version__", None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    except Exception:
        pass
    return "0.0.0"


VERSION = _read_version()


def _existing_paths(*relpaths: str) -> list[str]:
    out: list[str] = []
    for rel in relpaths:
        p = PROJECT_ROOT / rel
        if p.exists():
            out.append(str(p))
    return out


def _glob_existing(rel_glob: str) -> list[str]:
    return [str(p) for p in PROJECT_ROOT.glob(rel_glob) if p.exists()]


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out


RESOURCES = _existing_paths(
    "icon.ico",
    "bad_words.txt",
    "custom_vocab.json",
    "cryptolens_config.json",
    "gui_settings.json",
    "sample_settings.json",
    "sample_automations.json",
    "settings_with_samples.json",
    "voice_profiles",
    "custom_vocab_data",
    "resources",
)

RESOURCES = _dedupe_keep_order(RESOURCES + _glob_existing("VAICCS Exports/*.png"))


PY2APP_OPTIONS: dict = {
    # Disable argv_emulation for stability with Tk on modern macOS.
    "argv_emulation": False,
    "iconfile": _detect_or_build_iconfile(),
    "packages": [
        "vosk",
        "sounddevice",
        "_sounddevice_data",
        "soundfile",
        "numpy",
        "librosa",
        "hance",
        "transformers",
        "requests",
        "bs4",
        "PIL",
        "cryptography",
        "flask",
    ],
    "includes": [
        "tkinter",
        "tkinter.ttk",
        "encodings",
    ],
    "excludes": [
        "pytest",
        "unittest",
        "pydoc",
        "doctest",
        "PyInstaller",
        "wheel",
        "setuptools",
    ],
    "resources": RESOURCES,
    "site_packages": False,
    "semi_standalone": False,
    "plist": {
        "CFBundleName": "VAICCS Debug",
        "CFBundleDisplayName": "VAICCS Debug",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
    },
}


APPS = [
    {
        "script": "launcher_debug.py",
        "plist": {
            "CFBundleIdentifier": "com.dominic.vaiccs.debug",
            "CFBundleName": "VAICCS Debug",
            "CFBundleDisplayName": "VAICCS Debug",
        },
    }
]


def _run_setup() -> None:
    setup(
        name="VAICCS Debug",
        version=VERSION,
        app=APPS,
        options={"py2app": PY2APP_OPTIONS},
    )


if __name__ == "__main__":
    _run_setup()
