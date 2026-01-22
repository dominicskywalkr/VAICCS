# py2app build notes (macOS)

This project previously used PyInstaller via `gui.spec`. The equivalent build for macOS `.app` bundles is now `py2app` via `setup.py`.

## 1) Install build dependency

```bash
python3 -m pip install -U py2app
```

(You may also want: `python3 -m pip install -U setuptools wheel`.)

## 2) Build

### Production bundle

```bash
python3 setup.py py2app
```

### Debug bundle

```bash
python3 setup_debug.py py2app
```

### Fast iterative build (runs from source)

```bash
python3 setup.py py2app -A
```

Debug variant:

```bash
python3 setup_debug.py py2app -A
```

## 3) Output

- `dist/VAICCS.app` (or `dist/launcher.app` depending on py2app naming)
- `dist/VAICCS Debug.app` (or `dist/launcher_debug.app` depending on py2app naming)

## 4) If you hit missing-library/import errors

1. Rebuild with verbose output:

```bash
python3 setup.py py2app -v
```

2. Try enabling `site_packages` in `setup.py`:

- Set `"site_packages": True` in the `PY2APP_OPTIONS` dict.

This makes the bundle larger but often resolves issues with complex wheels containing native libraries.

3. If Vosk can’t locate `libvosk` inside the bundle:

- Ensure you have `vosk` installed from pip in the build environment.
- Keep `"packages": ["vosk", ...]` in `setup.py` so py2app copies package data.

## 5) Code signing / notarization

`py2app` only builds the `.app`. Signing and notarization are separate steps.

If you already have scripts under `scripts/`, we can adapt them to sign the `dist/*.app` output.
