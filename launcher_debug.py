"""Debug entrypoint.

Packaged as a separate macOS .app. Double-clicking it:
- enables verbose logging to a file
- opens Terminal and tails that log

Implementation detail: import `launcher` so PyInstaller bundles it.
"""

import os


def _main() -> None:
    os.environ.setdefault("VAICCS_DEBUG_TERMINAL", "1")
    os.environ.setdefault("VAICCS_LOG_LEVEL", "DEBUG")
    # Importing `launcher` runs the normal app startup path.
    import launcher  # noqa: F401


if __name__ == "__main__":
    _main()
