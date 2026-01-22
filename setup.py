"""py2app build script for VAICCS.

This replaces the old PyInstaller spec (gui.spec).

Note: py2app does not support building multiple app targets from a single
setup.py invocation. This file builds the main VAICCS app.

Build (recommended):
    python3 -m pip install -U py2app
    python3 setup.py py2app

Debug app:
    python3 setup_debug.py py2app
"""

from __future__ import annotations

import os
from pathlib import Path
import importlib.util
import sys
import subprocess
import tempfile

# Avoid failures copying macOS extended attributes (xattrs) from root-owned
# framework files into the bundle (can error with EPERM on some systems).
os.environ.setdefault("COPYFILE_DISABLE", "1")

from setuptools import setup


PROJECT_ROOT = Path(__file__).resolve().parent


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

    # Try to convert icon.ico -> VAICCS.icns (best-effort). If conversion fails,
    # we proceed without setting iconfile.
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
    """Best-effort version string for Info.plist."""
    try:
        import main as mainmod  # local import

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


# Resources copied into <App>.app/Contents/Resources.
# Keep this list focused on files the app expects to find via relative paths
# or wants to copy into per-user app data on first run.
RESOURCES = _existing_paths(
    # Bundle the in-app/Tk icon (.ico) for runtime use.
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

# Icon Composer exports (currently present as iOS-style themed PNGs). macOS app
# bundle icons are driven by .icns (or an Xcode-built asset catalog), but we
# still bundle these so the app can choose among them at runtime if desired.
RESOURCES = _dedupe_keep_order(RESOURCES + _glob_existing("VAICCS Exports/*.png"))


def _has_module(modname: str) -> bool:
    try:
        return importlib.util.find_spec(modname) is not None
    except Exception:
        return False


def _existing_packages(pkgs: list[str]) -> list[str]:
    """Filter a package list down to modules importable in the build env.

    py2app treats items in "packages" as required; including a missing module
    will fail the build.
    """
    out: list[str] = []
    for p in pkgs:
        if _has_module(p):
            out.append(p)
    return out


# Your PyInstaller spec forced Vosk to be included because it’s imported lazily.
# In py2app the most reliable analogue is listing it explicitly in "packages".
PY2APP_OPTIONS: dict = {
    # Disable argv_emulation for stability with Tk on modern macOS.
    # (argv_emulation uses legacy Carbon event processing and can interact
    # poorly with Tk initialization.)
    "argv_emulation": False,

    # # Must be .icns for macOS bundles.
    "iconfile": _detect_or_build_iconfile(),

    # Keep app non-terminal by default.
    "packages": _existing_packages([
        # speech / ML stack
        "vosk",
        "sounddevice",
        "_sounddevice_data",
        "numpy",
        # optional extras (included when installed)
        "soundfile",
        "librosa",
        "hance",
        "transformers",
        # misc dependencies
        "requests",
        "bs4",
        "PIL",
        "cryptography",
        "flask",
    ]),

    # Some dependencies do runtime imports; list a few common ones explicitly.
    "includes": [
        "tkinter",
        "tkinter.ttk",
        "encodings",
    ],

    # Avoid pulling in huge unused test suites.
    "excludes": [
        "pytest",
        "unittest",
        "pydoc",
        "doctest",
        "PyInstaller",
        "wheel",
        "setuptools",
    ],

    # Copy selected non-Python assets.
    "resources": RESOURCES,

    # If you hit missing-binary issues with complex wheels, set this to True.
    # It increases bundle size but often improves compatibility.
    "site_packages": False,

    # Prefer full bundles (safer, bigger) over semi-standalone.
    "semi_standalone": False,

    # You used no sandbox entitlements in PyInstaller; py2app doesn't sandbox by default.
    "plist": {
        "CFBundleName": "VAICCS",
        "CFBundleDisplayName": "VAICCS",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        # Required for macOS microphone permission prompts (TCC).
        "NSMicrophoneUsageDescription": "VAICCS needs microphone access for live closed captioning.",
    },
}


APPS = [
    {
        "script": "launcher.py",
        "plist": {
            "CFBundleIdentifier": "com.dominic.vaiccs",
            "CFBundleName": "VAICCS",
            "CFBundleDisplayName": "VAICCS",
            # Also include here to ensure it's present on the actual app target.
            "NSMicrophoneUsageDescription": "VAICCS needs microphone access for live closed captioning.",
        },
    }
]


def _run_setup() -> None:
    setup(
        name="VAICCS",
        version=VERSION,
        app=APPS,
        options={"py2app": PY2APP_OPTIONS},
    )


if __name__ == "__main__":
    _run_setup()
